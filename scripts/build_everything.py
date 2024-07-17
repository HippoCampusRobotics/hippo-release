#!/usr/bin/env python3

import glob
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import threading
from collections import namedtuple

import yaml

Pkg = namedtuple('Pkg', ['name', 'path', 'local_deps'])
ROS_DISTRO = os.environ.get('ROS_DISTRO')
WORKSPACE_DIR = os.getcwd()
DEBS = []


class Version:
    def __init__(self, version: str = None):
        self.major = 0
        self.minor = 0
        self.patch = 0
        if not version:
            version = '0.0.0'
        self.set_from_string(version)

    def set_from_string(self, version: str):
        try:
            x = re.search(r'^([0-9]+)\.([0-9]+)\.([0-9]+)$', version)
        except TypeError as e:
            raise ValueError(
                f'Could not parse version of pattern <n.n.n> in "{version}"'
            ) from e
        if not x:
            raise ValueError(
                f'Could not parse version of pattern <n.n.n> in "{version}"'
            )
        self.major = int(x.group(1))
        self.minor = int(x.group(2))
        self.patch = int(x.group(3))

    def __repr__(self):
        return f"Version('{self.major}.{self.minor}.{self.patch}')"

    def __str__(self):
        return f'{self.major}.{self.minor}.{self.patch}'

    def __eq__(self, other):
        return (
            (self.major == other.major)
            and (self.minor == other.minor)
            and (self.patch == other.patch)
        )

    def __lt__(self, other):
        if self.major > other.major:
            return False
        if self.major < other.major:
            return True

        if self.minor > other.minor:
            return False
        if self.minor < other.minor:
            return True

        return self.patch < other.patch

    def __le__(self, other):
        return self.__eq__(other) or self.__lt__(other)

    def __gt__(self, other):
        if self.major < other.major:
            return False
        if self.major > other.major:
            return True
        if self.minor < other.minor:
            return False
        if self.minor > other.minor:
            return True
        return self.patch > other.patch

    def __ge__(self, other):
        return self.__eq__(other) or self.__gt__(other)


class Pkg:
    def __init__(self, name: str, path: str):
        self.name = name
        self.dashed_name = self.name.replace('_', '-')
        self.deb_name = f'ros-{ROS_DISTRO}-{self.dashed_name}'
        self.path = path
        self.local_deps = []
        self.local_version = Version()
        self.remote_version = Version()

    def update_version(self):
        self._update_local_version()
        self._update_remote_version()

    def add_dependency(self, name: str):
        self.local_deps.append(name)

    def _update_remote_version(self):
        string = self._get_remote_version_string()
        if string:
            self.remote_version.set_from_string(string)
        else:
            print(
                f'{self.name} Could not determine remote version. '
                'Probably the package does not exist yet.'
            )
            self.remote_version.set_from_string('0.0.0')

    def _update_local_version(self):
        string = self._get_local_version_string()
        self.local_version.set_from_string(string)

    def _get_remote_version_string(self):
        name = self.deb_name
        cmd = f'apt-cache madison {name}'
        output = subprocess.check_output(cmd, shell=True, text=True)
        try:
            version_string = output.split('|')[1]
        except IndexError:
            return None
        # get versino number before the debian build increment
        return version_string.split('-')[0].replace(' ', '')

    def _get_local_version_string(self):
        cmd = f'colcon info {self.name}'
        output = subprocess.check_output(cmd, shell=True, text=True)
        lines = output.splitlines()
        for line in lines:
            if 'version: ' in line:
                return line.split('version: ', 1)[-1]
        return None

    def requires_rebuild(self):
        s_remote = str(self.remote_version)
        s_local = str(self.local_version)
        print(
            f'{self.name} remote version: {s_remote}, local version:{s_local}'
        )
        if self.remote_version >= self.local_version:
            print(
                'Version of the package to build is not newer than '
                'remote version. Skipping.'
            )
            return False
        return self.local_version > self.remote_version


def get_packages() -> list[Pkg]:
    cmd = ['colcon', 'list', '-t']
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE)
    lines = result.stdout.splitlines()
    pkgs = []
    for line in lines:
        name, path, _ = line.split('\t')
        path = os.path.join(WORKSPACE_DIR, path)
        pkgs.append(Pkg(name, path))
    threads = []
    print('Receiving package versions')
    for pkg in pkgs:
        threads.append(threading.Thread(target=pkg.update_version))
        threads[-1].start()

    for thread in threads:
        thread.join()
    print('Done')

    cmd = ['colcon', 'graph']
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE)
    lines = result.stdout.splitlines()
    n_pkgs = len(lines)
    for i, line in enumerate(lines):
        dep_substring = line[-n_pkgs:]
        indices = [
            idx for idx, c in enumerate(dep_substring) if (c == '*' or c == '.')
        ]
        if indices:
            for idx in indices:
                pkgs[idx].add_dependency(pkgs[i].name)
    return pkgs


def run_apt_update():
    cmd = 'apt update'
    subprocess.check_output(shlex.split(cmd), stderr=subprocess.STDOUT)


def run_rosdep_update():
    cmd = 'rosdep update'
    subprocess.check_output(shlex.split(cmd), stderr=subprocess.STDOUT)


def install_dependencies(pkg):
    cmd = f'rosdep install --from-paths {pkg.path} -y'
    subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)


def build_package(pkg: Pkg):
    env = os.environ.copy()
    dir = pkg.path
    cmd = 'bloom-generate rosdebian'
    shell = True
    if not shell:
        cmd = shlex.split(cmd)
    result = subprocess.Popen(cmd, shell=shell, cwd=dir, env=env)
    result.wait()
    print('Starting build process')
    cmd = 'export DEB_BUILD_OPTIONS="parallel=4";fakeroot debian/rules binary'
    if not shell:
        cmd = shlex.split(cmd)
    subprocess.check_output(cmd, shell=shell, cwd=dir, env=env)
    print('Build process done')


def install_package(pkg: Pkg):
    name = pkg.name.replace('_', '-')
    list_file = pathlib.Path(f'/etc/ros/rosdep/sources.list.d/50-{name}.list')
    yaml_file = pathlib.Path(f'/tmp/{name}.yaml')
    with list_file.open('w', encoding='utf-8') as f:
        f.write(f'yaml file://{str(yaml_file)}')

    data = {pkg.name: {'ubuntu': [pkg.deb_name]}}
    with yaml_file.open('w', encoding='utf-8') as f:
        yaml.dump(data, f)

    pattern = f'{pkg.path}/../{pkg.deb_name}*.deb'
    names = glob.glob(pattern)
    for name in names:
        print(name)
    cmd = f'apt install {names[0]}'
    subprocess.check_output(cmd, shell=True)
    p = pathlib.Path(names[0])
    out = pathlib.Path(f'/debs/{p.name}')
    shutil.move(str(p), str(out))
    print(f'Installed {names[0]}')


if __name__ == '__main__':
    # we do this only once. it is required because we are in a docker
    # environment and the sources list is deleted by convention
    print('Updating apt')
    run_apt_update()
    print('Updating rosdep')
    run_rosdep_update()
    pkgs = get_packages()
    for pkg in pkgs:
        print(f'\nProcessing {pkg.name}')
        if not pkg.requires_rebuild():
            continue
        print('Installing dependencies.')
        install_dependencies(pkg)
        build_package(pkg)
        print('Installing package')
        install_package(pkg)
        print('Updating rosdep')
        run_rosdep_update()
