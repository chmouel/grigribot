# -*- coding: utf-8 -*-
# Copyright (C) 2013 eNovance SAS <licensing@enovance.com>
#
# Author: Chmouel Boudjnah <chmouel@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import argparse
import logging
import os
import subprocess
import sys
import time

import gerritlib.gerrit
from oslo.config import cfg

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       "../"))

gerrit_opts = [
    cfg.StrOpt('host', help='Gerrit host.'),
    cfg.IntOpt('port', default=29418,
               help='Gerrit Port.'),
    cfg.StrOpt('username', default="",
               help='Username to connect to.'),
    cfg.StrOpt('key_file', default="",
               help='Private Key path.')
]
general_opts = [
    cfg.StrOpt('run_script', default="",
               help=('Script to spawn.')),
    cfg.ListOpt('watched_projects', default=[],
                help='Username to connect to.'),
    cfg.BoolOpt('voting_jobs', default=False,
                help='Wether to vote back the result.'),
    cfg.StrOpt('recheck_word', default="recheck",
               help='Recheck words to rekick the test.'),
    cfg.StrOpt('http_server', default="",
               help='HTTP server address to expose the link to.'),
    cfg.StrOpt('static_dir', default="",
               help='Directory where to store the logs.')
]


def list_opts():
    return [('general', general_opts),
            ('gerrit', gerrit_opts)]


CONF = cfg.CONF
cfg.CONF.register_opts(general_opts, group='general')
cfg.CONF.register_opts(gerrit_opts, group='gerrit')


class GrigriBot(object):
    def __init__(self):
        self.gerrit = None
        self.log = logging.getLogger('bottine')
        self.server = CONF.gerrit.host
        self.port = CONF.gerrit.port
        self.username = CONF.gerrit.username
        self.static_dir = CONF.general.static_dir
        self.http_server = CONF.general.http_server
        self.keyfile = os.path.expanduser(CONF.gerrit.key_file)
        self.run_script = os.path.expanduser(
            CONF.general.run_script)
        self.connected = False
        self.watched_projects = CONF.general.watched_projects
        self.recheck_word = CONF.general.recheck_word
        self.voting_jobs = CONF.general.voting_jobs

    def connect(self):
        # Import here because it needs to happen after daemonization
        try:
            self.gerrit = gerritlib.gerrit.Gerrit(
                self.server, self.username, self.port, self.keyfile)
            self.gerrit.startWatching()
            self.log.info('Start watching Gerrit event stream.')
            self.connected = True
        except Exception:
            self.log.exception('Exception while connecting to gerrit')
            self.connected = False
            # Delay before attempting again.
            time.sleep(1)

    def run_command(self, data):
        if 'change' not in data:
            return

        output_dir = "%s/%s/%s" % (self.static_dir,
                                   data['change']['number'],
                                   data['patchSet']['number'])

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        env = {'CHANGE_ID': data['change']['number'],
               'LOG_DIR': output_dir,
               'REF_ID': data['patchSet']['ref'],
               'AUTHOR': data['patchSet']['author']['email']}
        ret = subprocess.call([self.run_script], env=env, shell=True)
        self.log.info("script: %s has exited with return value of %s",
                      self.run_script, ret)

        if ret != 0:
            rets = "FAILED"
            retvote = '-1'
        else:
            rets = "SUCCESS"
            retvote = '+1'

        url = "%s/%s/%s/console.log" % (
            self.http_server, data['change']['number'],
            data['patchSet']['number'])

        if self.voting_jobs:
            self.gerrit.review(data['change']['project'],
                               "%s,%s" % (data['change']['number'],
                                          data['patchSet']['number']),
                               "run_tests.sh: %s: %s" % (rets, url),
                               action={'verified': retvote},)

    def _read(self, data):
        check = False
        if (data['type'] == 'comment-added' and
                data['comment'].endswith('\n' + self.recheck_word)):
            check = True
        elif data['type'] == 'patchset-created':
            check = True

        if data['change']['project'] not in self.watched_projects:
            check = False

        if check:
            self.log.info('Receiving event notification: %r' % data)
            self.run_command(data)

    def run(self):
        while True:
            while not self.connected:
                self.connect()
            try:
                event = self.gerrit.getEvent()
                self.log.info('Received event: %s' % event)
                self._read(event)
            except Exception:
                self.log.exception('Exception encountered in event loop')
                if not self.gerrit.watcher_thread.is_alive():
                    # Start new gerrit connection. Don't need to restart IRC
                    # bot, it will reconnect on its own.
                    self.connected = False


def setup_logging():
    logging.basicConfig(level=logging.INFO)


def parse_commandline_options(args=None):
    if args is None:
        args = sys.argv[1:]

    if os.path.exists("%s/etc/grigribot.ini" % BASEDIR):
        default_config_file = "%s/etc/grigribot.ini" % BASEDIR
    else:
        default_config_file = "/etc/grigribot/grigribot.conf"

    parser = argparse.ArgumentParser(prog="grigribot")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="store_true")
    parser.add_argument("-f", "--config-file", help="Config file",
                        default=default_config_file)
    return parser.parse_args(args)


def main():
    args = parse_commandline_options()
    CONF(default_config_files=[args.config_file])

    setup_logging()
    k = GrigriBot()
    k.run()

if __name__ == '__main__':
    main()
