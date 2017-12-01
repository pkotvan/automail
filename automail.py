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
                logger.warning(
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
        '-d',
        '--debug',
        action='store_const',
        const=logging.DEBUG,
        default=logging.WARN,
        help="Turn on debug output.")

    return parser.parse_args(cmdline)


def edit_template(tmpl):
    """
    Edit template in editor.
    """
    out = ""
    path = ""
    with tempfile.NamedTemporaryFile(mode='w+t', delete=False) as tmpf:
        path = tmpf.name
        logger.debug("Temporary file: %s", path)
        tmpf.write(tmpl)

    subprocess.run([os.environ["EDITOR"], path])

    with open(path, 'rt') as tmpf:
        tmpf.seek(0)
        out = tmpf.read()

    os.remove(path)

    return out


def render_message(path, variables, noedit=False):
    """Return rendered message."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(os.path.dirname(path)))
    tmpl = env.get_template(os.path.basename(path))

    # Get set of variables used in template.
    tmpl_src = env.loader.get_source(env, os.path.basename(path))[0]
    tmpl_vars = jinja2.meta.find_undeclared_variables(env.parse(tmpl_src))

    # Preserve undeclared variables.
    missing_vars = tmpl_vars - set(variables.keys())
    for var in missing_vars:
        variables[var] = "{{{{ {} }}}}".format(var)

    if len(missing_vars) == 0 and noedit:
        logger.debug(
            "No missing vars + noedit on command line. Continue without manual edit."
        )
        return tmpl.render(variables)
    else:
        logger.debug("Missing variables: %s", missing_vars)
        partial = tmpl.render(variables)
        return edit_template(partial)


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

    logger.debug('Message headers: %s', hdrs)
    return hdrs, body


def send_message(cfg, msg):
    """
    Send the message.
    """
    host = cfg['general']['host']
    try:
        port = cfg['general']['port']
    except KeyError:
        port = 0

    logger.debug("Host: %s", host)

    srv = smtplib.SMTP(host, port=port)
    srv.send_message(msg)
    srv.quit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARN)
    logger = logging.getLogger(__name__)
    args = parse_arguments(sys.argv[1:])
    logging.basicConfig(level=args.debug)
    logger.debug("Command line arguments: %s", args)

    config = configparser.ConfigParser()
    with open(os.path.expanduser(args.config)) as cfgfile:
        config.read_file(cfgfile)
    logger.debug("Host: %s", config['general']['host'])

    message = render_message(args.template, args.jinja_vars, args.noedit)
    headers, content = parse_message(message)
    mail = email.message.EmailMessage()
    mail.set_content(content)
    for header in headers:
        mail[header] = headers[header]
        logger.debug("Adding header: %s: %s", header, headers[header])

    if args.dryrun:
        print("Message headers: \n{}\n".format(headers))
        print("Message content: \n{}".format(content))
        sys.exit()

    send_message(config, mail)
