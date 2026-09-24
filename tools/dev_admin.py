#!/usr/bin/python3
"""Privileged setup helpers shared by the first-boot wizard.

run_as_root/password_ok mirror the shell's sudo -S pattern: the password
travels stdin, nothing reads /etc/shadow. The command builders are pure
so tests can check the exact argv the wizard will run.
"""
import subprocess


def run_as_root(argv, password, sudo='sudo'):
    """Run one command as root through sudo -S; True when it succeeds."""
    if not isinstance(argv, list) or not argv or not all(argv):
        raise ValueError('run_as_root needs a non-empty argv list')
    result = subprocess.run([sudo, '-S', '-k', '-u', 'root'] + argv,
                            input=password + '\n', text=True,
                            capture_output=True, timeout=20)
    return result.returncode == 0


def password_ok(password, sudo='sudo'):
    """Verify a sudo password with `sudo -k -u root true`."""
    return run_as_root(['true'], password, sudo)


def shell_quote(text):
    """One safely-single-quoted shell word."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def chpasswd_command(user, password):
    """The argv that sets a user's password through busybox chpasswd."""
    line = '%s:%s' % (user, password)
    return ['sh', '-c', 'printf %s | chpasswd' % shell_quote(line)]


def adduser_command(user, home='/home', shell='/bin/sh'):
    """The argv that creates a locked, no-password user."""
    return ['adduser', '-D', '-h', home + '/' + user, '-s', shell, user]


def timezone_command(zone, base='/usr/share/zoneinfo'):
    """The argv that installs a zone as the system local time."""
    return ['cp', base + '/' + zone, '/etc/localtime']
