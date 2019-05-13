#!/opt/scalarizr/embedded/bin/python

nginx_config_file = '/etc/nginx/nginx.conf'
nginx_reload_command = 'service nginx restart'
nginx_config_template = """
user   www-data;
worker_processes   auto;
pid   /run/nginx.pid;

events  {
   worker_connections   768;
   # multi_accept on;
}

http  {
    sendfile   on;
    tcp_nopush   on;
    tcp_nodelay   on;
    keepalive_timeout   65;
    types_hash_max_size   2048;

    include   /etc/nginx/mime.types;
    default_type   application/octet-stream;

    ssl_protocols   TLSv1 TLSv1.1 TLSv1.2;
    ssl_prefer_server_ciphers   on;

    access_log   /var/log/nginx/access.log;
    error_log   /var/log/nginx/error.log;

    gzip   on;
    gzip_disable   "msie6";

    include   /etc/nginx/conf.d/*.conf;
    gzip_vary   on;
    gzip_proxied   any;
    gzip_types   text/plain text/css application/json application/x-javascripttext/xml application/xml application/xml+rss text/javascript;
    server  {
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        client_max_body_size   10m;
        client_body_buffer_size   128k;
        proxy_buffering   on;
        proxy_connect_timeout   15;
        proxy_intercept_errors   on;
        ssl_session_timeout   10m;
        ssl_session_cache   shared:SSL:10m;
        ssl_ciphers   ALL:!ADH:!EXPORT56:RC4+RSA:+HIGH:+MEDIUM:+LOW:+SSLv2:+EXP;
        ssl_prefer_server_ciphers   on;
        listen   80;
        server_name   localhost;
        location / {
            proxy_pass   http://app_upstream;
        }
    }
    upstream app_upstream {
    {% for server in servers %}
        server {{ server.get('internal-ip', server.get('external-ip')) }}:8000;
    {% endfor %}
    }
}
"""

import copy
import json
import logging
import os
import subprocess
import sys

from xml.etree import ElementTree

try:
    import jinja2
except ImportError:
    import pip
    pip.main(['install', 'jinja2'])
    import jinja2

def main():
    config_text = generate_nginx_config()
    logging.info('Configuration:\n%s', config_text)
    logging.info('Writing configuration to config file: %s', nginx_config_file)
    with open(nginx_config_file, 'w') as outfile:
        outfile.write(config_text)
    logging.info('Done, reloading nginx')
    subprocess.call(nginx_reload_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def generate_nginx_config():
    template = jinja2.Template(nginx_config_template)
    return template.render(servers=get_backend_servers())

def get_backend_servers():
    f = FarmRoleEngine()
    all_roles = f.list_roles()
    # Finding the webapp role
    for role in all_roles:
        if 'app' in role.lower():
            servers = f.get_farm_role_hosts(role)
            return servers
    else:
        raise NoSuchRoleException('Cannot find webapp role')


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


logging.basicConfig(level=logging.DEBUG)
main()

