#!/opt/scalarizr/embedded/bin/python
#coding:utf-8

# This script queries the state of MySQL servers and configures the
# WebApp

import os
import subprocess
import copy
import operator
import time
import json

from xml.etree import ElementTree


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
        args = ['-q', 'list_roles']
        if with_initializing:
            args.append('showInitServers=1')
        t = self._szradm(args)
        roles = t.find('roles')
        hosts = []
        for role in roles:
            hosts += [host.attrib for host in role.find("hosts").findall("host")]
        return hosts



def prepare_config_files(engine):
    all_roles = engine.list_roles()
    for role in all_roles:
        if 'sql' in role.lower() or 'db' in role.lower():
            mysql_role = role
            break
    else:
        raise NoSuchRoleException('Cannot find MySQL role')


    # Create configuration files
    files = []

    # Start with MySQL configuration
    # Note: this is very unsafe. Don't use this in production - this is only
    # an example. You should use a secret management tool to configure the MySQL
    # credentials in a real deployment.
    files.append(("mysql-username", 'root'))
    files.append(("mysql-password", ''))

    # Find the master
    for i in range(10):
        # Retrieve the list of MySQL hosts
        mysql_hosts = engine.get_farm_role_hosts(mysql_role)
        all_server_ids = [h['scalr-server-id'] for h in mysql_hosts]
        master_id = get_current_mysql_master()
        if master_id in all_server_ids:
            # A master was found, continue the configuration
            break
        # Wait 5 seconds and retry
        print ('No master found, waiting for a new one...')
        time.sleep(5)
    else:
        # No master found, return an empty configuration
        files.append(('mysql-master', ''))
        files.append(('mysql-slave', ''))
        return files

    master = [h for h in mysql_hosts if h['scalr-server-id'] == master_id][0]
    slaves = [h for h in mysql_hosts if h['scalr-server-id'] != master_id]
    print (master, slaves)

    # Create a configuration file with the MySQL master's IP
    files.append(("mysql-master", master['internal-ip'] or master['external-ip']))

    # Add a configuration file with MySQL slave IPs
    files.append(("mysql-slave", '\n'.join([s['internal-ip'] or s['external-ip'] for s in slaves])))

    print (files)
    return files


def get_current_mysql_master():
    # Don't trust env, refresh GVs from Scalr each time
  global_variables_json = subprocess.check_output(['szradm', 'queryenv', '--format=json', 'list-global-variables'])
    
  global_variables = json.loads(global_variables_json.decode('utf-8'))
  return global_variables['variables']['values'].get('MYSQL_MASTER', '')

def main():
    engine = FarmRoleEngine()
    config_dir = "/var/config"

    try:
        os.mkdir(config_dir)
    except OSError:
        pass

    for filename, contents in prepare_config_files(engine):
        with open(os.path.join(config_dir, filename), "w") as f:
            f.write(contents or "")


if __name__ == "__main__":
    main()
