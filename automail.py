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

# Dictionary with default configuration values.
CONFIG_DEFAULTS = {'starttls': 'yes', 'port': '0'}


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

    # Arguments with both short and long option strings.
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
        '-n',
        '--noninteractive',
        action='store_true',
        help="Do not edit template manually if possible.")
    parser.add_argument(
        '-s', '--server', help="Use specific server from the config.")
    parser.add_argument(
        '-p', '--port', type=int, default=0, help="Use specific port.")

    # Arguments with only long option strings.
    parser.add_argument('--signature', help="Path to signature text.")
    parser.add_argument(
        '--dryrun', action='store_true', help="Do not send the message.")
    parser.add_argument(
        '--starttls',
        action='store_true',
        default=None,
        help=
        "Put the SMTP connection in TLS (Transport Layer Security). Default.")
    parser.add_argument(
        '--nostarttls',
        action='store_false',
        dest='starttls',
        default=None,
        help="Do not use STARTTLS.")
    parser.add_argument('--host', help="Server address.")

    parser.add_argument(
        '-d',
        '--debug',
        action='store_const',
        const=logging.DEBUG,
        default=logging.WARN,
        help="Turn on debug output.")

    # Positional arguments are parsed with custom action defined by StoreDict
    # class. All positional arguments are used to replate jinja variables used
    # in templates.
    parser.add_argument(
        'jinja_vars',
        nargs='*',
        action=StoreDict,
        metavar='template_variable=variable_value',
        help="Template variables like 'name=john'")

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


def load_config(path):
    """
    Load configuration file and add default values.
    """
    cfg = configparser.ConfigParser()
    cfg['DEFAULT'] = CONFIG_DEFAULTS
    with open(os.path.expanduser(path)) as cfgfile:
        cfg.read_file(cfgfile)
    return cfg


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


def send_message(arg, msg):
    """
    Send the message.
    """
    LOGGER.debug("Connecting to %s", arg.host)
    smtp = smtplib.SMTP(arg.host, port=arg.port)
    if arg.starttls:
        LOGGER.debug("Use starttls.")
        smtp.starttls()

    smtp.send_message(msg)
    smtp.quit()


def add_signature(sigpath, msg):
    """
    Add signature to the message.
    """
    with open(os.path.expanduser(sigpath)) as sig:
        return msg + '\n' + sig.read()


def apply_cfg(arg):
    """
    Apply configuration.
    """
    LOGGER.debug("Loading configuration file: %s", arg.config)
    cfg = load_config(arg.config)

    if not arg.server:
        arg.server = cfg['general']['server']

    srvcfg = cfg[arg.server]

    if arg.starttls is None:
        arg.starttls = srvcfg.getboolean('starttls')

    if not arg.host:
        arg.host = srvcfg['host']

    if not arg.port:
        arg.port = srvcfg.getint('port')

    return arg


def main():
    """
    Main function.
    """
    args = parse_arguments(sys.argv[1:])
    LOGGER.setLevel(args.debug)
    LOGGER.debug("Command line arguments: %s", args)
    apply_cfg(args)
    LOGGER.debug("Configuration applied: %s", args)

    tmpl, tmpl_vars = load_template(args.template)

    # List jinja variables and exit.
    if args.list:
        print("Undefined template variables: {}".format(tmpl_vars))
        return

    missing_vars = tmpl_vars - set(args.jinja_vars.keys())
    LOGGER.debug("Missing variables: %s", missing_vars)

    if args.noninteractive:
        if missing_vars:
            LOGGER.error("Missing jinja variables in noninteractive mode: %s",
                         missing_vars)
            return 1
        if args.signature:
            message = add_signature(args.signature, tmpl.render(
                args.jinja_vars))
        else:
            message = tmpl.render(args.jinja_vars)

        # Print the message in noninteractive mode if dryrun is enabled.
        if args.dryrun:
            print(message)
    else:
        for var in missing_vars:
            args.jinja_vars[var] = "{{{{ {} }}}}".format(var)

        if args.signature:
            message = edit_template(
                add_signature(args.signature, tmpl.render(args.jinja_vars)))
        else:
            message = edit_template(tmpl.render(args.jinja_vars))

        print(message)
        if not args.dryrun:
            if not yes_no("\nDo you really want to send the message?", "no"):
                return

    headers, content = parse_message(message)

    mail = email.message.EmailMessage()
    mail.set_content(content)
    for header in headers:
        mail[header] = headers[header]
        LOGGER.debug("Adding header: %s: %s", header, headers[header])

    if not args.dryrun:
        send_message(args, mail)
    else:
        LOGGER.debug("Dry run enabled, message not sent.")


if __name__ == "__main__":
    sys.exit(main())
