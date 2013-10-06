# -*- coding: utf-8 -*-

import subprocess
import os
import re
import logging
import errno

from .config import Config
from .utils import safe_makedirs, value_interpolate, construct_proxy_command

class AdvancedSshConfig(object):

    def __init__(self, hostname=None, port=None, configfile=None,
                 verbose=False, dry_run=False, proxy_type='nc',
                 timeout=180):

        self.verbose, self.dry_run = verbose, dry_run
        self.hostname, self.port = hostname, port
        self.proxy_type, self.timeout = proxy_type, timeout

        self.log = logging.getLogger('')

        # Initializes the Config object
        configfiles = [
            '/etc/ssh/config.advanced',
            '~/.ssh/config.advanced',
            ]
        if configfile:
            configfiles += configfile
        self.config = Config(configfiles=configfiles)

    def debug(self, string=None):
        self.log.debug(string and string or '')

    @property
    def controlpath_dir(self):
        controlpath = self.config.get('controlpath', 'default', '/tmp')
        dir = os.path.dirname(os.path.expanduser(controlpath))
        dir = os.path.join(dir, self.hostname)
        dir = os.path.dirname(dir)
        return dir

    def get_routing(self):
        routing = {}
        safe_makedirs(self.controlpath_dir)

        section = None
        for sect in self.config.parser.sections():
            if re.match(sect, self.hostname):
                section = sect

        self.debug('section \'{}\' '.format(section))

        # Parse special routing
        path = self.hostname.split('/')

        args = {}
        options = {
            'p': 'Port',
            'l': 'User',
            'h': 'Hostname',
            'i': 'IdentityFile'
            }
        default_options = {
            'p': str(self.port),
            'h': path[0]
            }
        updated = False
        for key in options:
            cfval = self.config.get(options[key], path[0], default_options.get(key))
            value = value_interpolate(cfval)
            if cfval != value:
                updated = True
                self.config.parser.set(section, options[key], value)
                args[key] = value

            self.debug('get (-%-1s) %-12s : %s' % (key, options[key], value))
            if value:
                args[key] = value

        # If we interpolated any keys
        if updated:
            self._update_sshconfig()
            self.log.debug('Config updated. Need to restart SSH!?')

        self.debug('args: {}'.format(args))
        self.debug()

        self.debug('hostname    : {}'.format(self.hostname))
        self.debug('port        : {}'.format(self.port))
        self.debug('path        : {}'.format(path))
        self.debug('path[0]     : {}'.format(path[0]))
        self.debug('path[1:]    : {}'.format(path[1:]))
        self.debug('args        : {}'.format(args))

        self.debug()
        routing['verbose'] = self.verbose
        routing['proxy_type'] = self.proxy_type
        routing['gateways'] = self.config.get('Gateways', path[-1], 'direct').strip().split(' ')
        routing['reallocalcommand'] = self.config.get('RealLocalCommand', path[-1], '').strip().split(' ')
        self.debug('reallocalcommand : {}'.format(routing['reallocalcommand']))
        self.debug('gateways         : {}'.format(', '.join(['gateways'])))
        routing['gateway_route'] = path[1:]
        routing['hostname'] = path[0]
        #routing['args'] = args
        routing['port'] = self.port or args['p'] or 22
        routing['proxy_command'] = construct_proxy_command(routing)

        self.debug()
        self.debug('Routing:')
        for k, v in routing.iteritems():
            self.debug('  {0}: {1}'.format(k, v))
        self.debug()

        return routing

    def connect(self, routing):
        for gateway in routing['gateways']:
            if gateway != 'direct':
                routing['gateway_route'] += [gateway]
            cmd = []
            if len(routing['gateway_route']):
                cmd += ['ssh', '/'.join(routing['gateway_route'])]

            cmd += routing['proxy_command']

            self.debug('cmd         : {}'.format(cmd))
            self.debug('================')
            self.debug()

            if not self.dry_run:
                ssh_process = subprocess.Popen(map(str, cmd))
                reallocalcommand_process = None
                if len(routing['reallocalcommand'][0]):
                    reallocalcommand_process = subprocess.Popen(routing['reallocalcommand'])
                if ssh_process.wait() != 0:
                    self.log.critical('There were some errors')
                if reallocalcommand_process is not None:
                    reallocalcommand_process.kill()

    def update_sshconfig(self, write=True):
        config = []

        for section in self.config.parser.sections():
            if section != 'default':
                host = section
                host = re.sub(r'\.\*', '*', host)
                host = re.sub(r'\\\.', '.', host)
                config += ['Host {}'.format(host)]
                special_keys = (
                    'hostname',
                    'gateways',
                    'reallocalcommand',
                    'remotecommand'
                    )
                items = self.config.parser.items(section, False, {'Hostname': host})
                for key, value in items:
                    if key not in special_keys:
                        if key == 'alias':
                            key = 'hostname'
                        config += ['  {} {}'.format(key, value)]
                config += ['']

        config += ['Host *']
        for key, value in self.config.parser.items('default'):
            if key not in ('hostname', 'gateways', 'includes'):
                config += ['  {} {}'.format(key, value)]

        if write:
            fhandle = open(os.path.expanduser('~/.ssh/config'), 'w+')
            fhandle.write('\n'.join(config))
            fhandle.close()
        else:
            print '\n'.join(config)