#!/usr/bin/env python3
"""
Simple program to send emails rendered from jinja2templates.

Copyright (C) 2017 tlamer <tlamer@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import sys
import os
import os.path
import argparse
import logging
import tempfile
import subprocess
import configparser
import smtplib
import email.message
import jinja2
import jinja2.meta

logging.basicConfig(level=logging.WARN)
LOGGER = logging.getLogger(__name__)


def yes_no(question, default="yes"):
    """
    Get yes/no input from user.
    """
    valid = {
        "yes": True,
        "y": True,
        "no": False,
        "n": False,
    }

    if default is None:
        prompt = "[y/n]"
    elif default == "yes":
        prompt = "[Y/n]"
    elif default == "no":
        prompt = "[y/N]"
    else:
        raise ValueError("invalid default answer: {}".format(default))

    while True:
        sys.stdout.write("{} {} ".format(question, prompt))
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]


class StoreDict(argparse.Action):
    """
    Custom action to store command line arguments as dictionary.
    """

    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        super(StoreDict, self).__init__(
            option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        my_dict = {}
        for item in values:
            try:
                key, val = item.split('=')
            except ValueError:
                LOGGER.warning(
                    "Could not parse '%s'. Parameter in 'key=value' format is expected.",
                    item)
                continue
            my_dict[key] = val
        setattr(namespace, self.dest, my_dict)


def parse_arguments(cmdline):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Send emails generated from templates.")
    parser.add_argument(
        '-c',
        '--config',
        default='~/.automailrc',
        help="Use different configuration file. Default is ~/.automailrc")
    parser.add_argument(
        '-t', '--template', required=True, help="Template path.")
    parser.add_argument(
        '-l',
        '--list',
        action='store_true',
        help="List template variables and exit.")
    parser.add_argument(
        'jinja_vars',
        nargs='*',
        action=StoreDict,
        metavar='template_variable=variable_value',
        help="Template variables like 'name=john'")
    parser.add_argument(
        '--dryrun',
        action='store_true',
        help="Do not send the message, just print it to stdout and exit.")
    parser.add_argument(
        '-n',
        '--noedit',
        action='store_true',
        help="Do not edit template manually if possible.")
    parser.add_argument(
        '-H', '--host', help="Use specific host from the config.")
    parser.add_argument(
        '-d',
        '--debug',
        action='store_const',
        const=logging.DEBUG,
        default=logging.WARN,
        help="Turn on debug output.")

    return parser.parse_args(cmdline)


def edit_template(template):
    """
    Edit template in editor.
    """
    out = ""
    path = ""
    with tempfile.NamedTemporaryFile(mode='w+t', delete=False) as tmpf:
        path = tmpf.name
        LOGGER.debug("Temporary file: %s", path)
        tmpf.write(template)

    subprocess.check_call([os.environ["EDITOR"], path])

    with open(path, 'rt') as tmpf:
        tmpf.seek(0)
        out = tmpf.read()

    os.remove(path)

    return out


def load_template(path):
    """
    Load jinja2 template and return the template object and the set of
    variables used in the template.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(os.path.dirname(path)))
    template = env.get_template(os.path.basename(path))

    # Get set of variables used in template.
    src = env.loader.get_source(env, os.path.basename(path))[0]
    vrs = jinja2.meta.find_undeclared_variables(env.parse(src))

    return template, vrs


def parse_message(msg):
    """
    Parse headers and message content.
    """
    hdrs = {}
    body = ""
    index = 1
    lines = msg.split('\n')

    for line in lines:
        if line == '':
            break
        index += 1
        key, val = line.split(':')
        hdrs[key.strip()] = val.strip()
    body = '\n'.join(lines[index:])

    LOGGER.debug('Message headers: %s', hdrs)
    return hdrs, body


def send_message(cfg, hst, msg):
    """
    Send the message.
    """
    if hst:
        host = cfg[hst]
    else:
        host = cfg[cfg['general']['server']]

    try:
        port = host['port']
    except KeyError:
        port = 0

    srv = smtplib.SMTP(host['host'], port=port)
    srv.send_message(msg)
    srv.quit()


def main():
    """
    Main function.
    """
    args = parse_arguments(sys.argv[1:])
    logging.basicConfig(level=args.debug)
    LOGGER.debug("Command line arguments: %s", args)

    config = configparser.ConfigParser()
    with open(os.path.expanduser(args.config)) as cfgfile:
        config.read_file(cfgfile)
    LOGGER.debug("Host: %s", config['general']['default'])

    tmpl, tmpl_vars = load_template(args.template)

    # List jinja variables and exit.
    if args.list:
        print("Undefined template variables: {}".format(tmpl_vars))
        return

    missing_vars = tmpl_vars - set(args.jinja_vars.keys())

    if args.noedit:
        if missing_vars:
            LOGGER.error("Missing jinja variables in batch mode: %s",
                         missing_vars)
            return 1
        message = tmpl.render(args.jinja_vars)
    else:
        for var in missing_vars:
            args.jinja_vars[var] = "{{{{ {} }}}}".format(var)
        message = edit_template(tmpl.render(args.jinja_vars))

        print(message)
        if not yes_no("\nDo you really want to send the message?", "no"):
            return

    headers, content = parse_message(message)

    # Dryrun: print message headers and contents and exit.
    if args.dryrun:
        print("Message headers: \n{}\n".format(headers))
        print("Message content: \n{}".format(content))
        return

    mail = email.message.EmailMessage()
    mail.set_content(content)
    for header in headers:
        mail[header] = headers[header]
        LOGGER.debug("Adding header: %s: %s", header, headers[header])

    send_message(config, args.host, mail)


if __name__ == "__main__":
    sys.exit(main())
