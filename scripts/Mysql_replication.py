#!/opt/scalarizr/embedded/bin/python

import copy
import json
import logging
import os
import subprocess
import sys
import operator
import time
import random
import string

from xml.etree import ElementTree


def main():
    # Check if I'm terminating
    if os.getenv('SCALR_EVENT_NAME', '') == 'BeforeHostTerminate':
        if os.getenv('SCALR_EVENT_SERVER_ID', '') == os.getenv('SCALR_SERVER_ID', ''):
            logging.info('I\'m dying, bb all')
            return
    try:
        e = FarmRoleEngine()
        my_farm_role = os.getenv('SCALR_FARM_ROLE_ID')
        my_id = os.getenv('SCALR_SERVER_ID')
        # Looping to make sure we end up in a valid state.
        # The server we chose at master in a previous iteration of the loop might have been deleted before we can configure it.
        # In that case we will choose another one.
        while True:
            servers = e.get_all_farm_servers(True)
            mysql_master_id = get_current_mysql_master()
            for server in servers:
                if server['scalr-server-id'] == mysql_master_id:
                    logging.info('MySQL master found: {}. Current status: {}'.format(mysql_master_id, server['status']))
                    if mysql_master_id == my_id:
                        # I'm the master now!
                        logging.info('I\'m the master. Canceling replication if I used to be a slave')
                        setup_as_master()
                    else:
                        logging.info('Configuring replication from the master')
                        setup_as_slave(server['internal-ip'] or server['external-ip'])
                    return

            # Master doesn't exist. Elect a new one.
            logging.info('No MySQL master found. Electing a new one')
            mysql_servers = [s for s in servers if s['farm_role_id'] == my_farm_role]
            # We prefer a running server over an initializing one, and we take the one with the lowest index
            running_servers = sorted([s for s in mysql_servers if s['status'] == 'Running'], key=operator.itemgetter('index'))
            initializing_servers = sorted([s for s in mysql_servers if s['status'] != 'Running'], key=operator.itemgetter('index'))
            if len(running_servers) > 0:
                proposed_master = running_servers[0]['scalr-server-id']
            elif len(initializing_servers) > 0:
                proposed_master = initializing_servers[0]['scalr-server-id']
            else:
                # No servers found. What am I?
                raise Exception('No potential master found')
            logging.info('Elected master: {}'.format(proposed_master))
            elect_master(proposed_master)
            # Sleep for a bit to prevent races (other server setting a different master in parallel).
            # Possible if other server got a different server list.
            time.sleep(10)
            # And go back to the beginning of the loop, read the master from GV and carry on configuring

    except:
        logging.exception('Error')
        raise


def setup_as_master():
    o = subprocess.check_output(['mysql', '-e', 'STOP SLAVE;'], stderr=subprocess.STDOUT)
    logging.info('STOP SLAVE output:\n{}'.format(o))
    # Slaves will configure replication to me

def setup_as_slave(master_ip):
    # Theory:
    # If I was already replicating, just switch masters
    # If I wasn't replicating, I'm just starting. Get all the data.
    # (I can't go from master to slave without dying - if I'm dying, the check at the beginning of main prevents all this from running)
    # Practice: 
    # Drop all data and sync back with master from the beginning each time - this will work because for demos we have very little data, 
    # and demos run for less time than the binlog rotation time (10 days)
    # This avoids the need to stop the master, take a snapshot, and resume replication from the snapshot.
    logging.info('Stopping replication:\n{}'.format(
        subprocess.check_output(['mysql', '-e', 'STOP SLAVE;'], stderr=subprocess.STDOUT)
    ))
    try:
        logging.info('Dropping all data:\n{}'.format(
            subprocess.check_output(['mysql', '-e', 'DROP DATABASE ScalrTest;'], stderr=subprocess.STDOUT)
        ))
    except:
        logging.info("Couldn't drop database ScalrTest, most likely because it doesn't exist")
        pass
    my_ip = os.getenv('SCALR_INTERNAL_IP') or os.getenv('SCALR_EXTERNAL_IP')
    mysql_user = 'root'
    mysql_password = ''
    repl_password = os.getenv('MYSQL_SERVER_REPL_PASSWORD', '')
    if not repl_password:
        repl_password = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(20))
        save_repl_password(repl_password)

    cmd = [
        'mysqlreplicate',
        '--master',
        '{}:{}@{}:3306'.format(mysql_user, mysql_password, master_ip),
        '--slave',
        '{}:{}@{}:3306'.format(mysql_user, mysql_password, my_ip),
        '--rpl-user=rpl_user:{}'.format(repl_password),
        '-vv',
        '--start-from-beginning'
    ]
    logging.info('Restarting replication from the beginning:\n{}'.format(subprocess.check_output(cmd, stderr=subprocess.STDOUT)))

def get_current_mysql_master():
    # Don't trust env, refresh GVs each time
    global_variables_json = subprocess.check_output(['szradm',
                                                     'queryenv',
                                                     '--format=json',
                                                     'list-global-variables'])
    global_variables = json.loads(global_variables_json.decode('utf-8'))
    return global_variables['variables']['values'].get('MYSQL_MASTER', '')


def save_repl_password(pw):
    r = subprocess.check_output(['szradm',
                                 'queryenv',
                                 '--format=json',
                                 'set-global-variable',
                                 'scope=server',
                                 'param-name=MYSQL_SERVER_REPL_PASSWORD',
                                 'param-value={}'.format(pw)], stderr=subprocess.STDOUT)
    logging.info('Result of setting MYSQL_SERVER_REPL_PASSWORD var:\n{}'.format(r))


def elect_master(server_id):
    r = subprocess.check_output(['szradm',
                                 'queryenv',
                                 '--format=json',
                                 'set-global-variable',
                                 'scope=farm',
                                 'param-name=MYSQL_MASTER',
                                 'param-value={}'.format(server_id)], stderr=subprocess.STDOUT)
    logging.info('Result of setting MYSQL_MASTER var:\n{}'.format(r))


class FarmRoleException(Exception):
    pass


class NoSuchRoleException(Exception):
    pass


class FarmRoleEngine(object):
    def _szradm(self, params):
        """
        Make a call to szradm, check for errors, and return the output
        """
        params = copy.copy(params)
        params.insert(0, "/usr/local/bin/szradm")
        proc = subprocess.Popen(params, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.wait():
            raise FarmRoleException("Unable to access szradm: %s", proc.stderr.read())
        return ElementTree.parse(proc.stdout)

    def _get_farm_role(self, alias):
        """
        Retrieve the Farm Role matching a selected alias in the
        current Farm
        """
        args = ["-q", "list-roles"]
        t = self._szradm(args)
        all_roles = t.find("roles")
        for role in all_roles:
            if alias == role.attrib["alias"]:
                return role
        raise NoSuchRoleException

    def list_roles(self):
        """
        Returns the list of the aliases of all the roles in the current Farm
        """
        args = ["-q", "list-roles"]
        t = self._szradm(args)
        all_roles = t.find("roles")
        return [role.attrib["alias"] for role in all_roles]


    def get_farm_role_id(self, alias):
        """
        Get the ID for the Farm Role matching a selected alias in the
        current Farm
        """
        role = self._get_farm_role(alias)
        return int(role.attrib["id"])

    def get_farm_role_hosts(self, alias):
        """
        Get a list of Hosts for the Farm Role matching a selected alias
        in the current Farm
        Returns a list of dicts. Each dict represents a host
        """
        role = self._get_farm_role(alias)
        hosts = role.find("hosts")
        return [host.attrib for host in hosts.findall("host")]

    def get_all_farm_servers(self, with_initializing=True):
        """
        Returns the list of all the servers that are running in the current Farm.
        @param with_initializing bool Include servers in initializing state.
        """
        args = ['-q', 'list-roles']
        if with_initializing:
            args.append('showInitServers=1')
        t = self._szradm(args)
        roles = t.find('roles')
        hosts = []
        for role in roles:
            hosts += [dict(host.attrib, farm_role_id=role.attrib['id']) for host in role.find("hosts").findall("host")]
        return hosts


logging.basicConfig(level=logging.DEBUG)
main()


