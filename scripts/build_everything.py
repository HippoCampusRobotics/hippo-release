#!/usr/bin/env python3

import glob
import os
import pathlib
import shlex
import shutil
import subprocess
from collections import namedtuple

import yaml

Pkg = namedtuple('Pkg', ['name', 'path', 'local_deps'])
ROS_DISTRO = os.environ.get('ROS_DISTRO')
WORKSPACE_DIR = os.getcwd()
DEBS = []


class Pkg:
    def __init__(self, name: str, path: str):
        self.name = name
        self.dashed_name = self.name.replace('_', '-')
        self.deb_name = f'ros-{ROS_DISTRO}-{self.dashed_name}'
        self.path = path
        self.local_deps = []

    def add_dependency(self, name: str):
        self.local_deps.append(name)

    def get_remote_version_string(self):
        name = self.deb_name
        cmd = f'apt-cache madison {name}'
        output = subprocess.check_output(cmd, shell=True, text=True)
        try:
            version_string = output.split('|')[1]
        except IndexError:
            return None
        # get versino number before the debian build increment
        return version_string.split('-')[0].replace(' ', '')

    def get_local_version_string(self):
        cmd = f'colcon info {self.name}'
        output = subprocess.check_output(cmd, shell=True, text=True)
        lines = output.splitlines()
        for line in lines:
            if 'version: ' in line:
                return line.split('version: ', 1)[-1]
        return None

    def requires_rebuild(self):
        remote = self.get_remote_version_string()
        if not remote:
            print(
                'Could not determine remote version. '
                'Probably the package does not exist yet.'
            )
            return True
        local = self.get_local_version_string()
        print(f'remote version: {remote}, local version:{local}')
        if remote == local:
            print('Local version and remote version are identical. Skipping.')
            return False
        rmajor, rminor, rpatch = [int(x) for x in remote.split('.')]
        lmajor, lminor, lpatch = [int(x) for x in local.split('.')]
        if rmajor > lmajor:
            print('Local version is older than remote version! Skipping.')
            return False
        if rmajor < lmajor:
            return True
        if rminor > lminor:
            print('Local version is older than remote version! Skipping.')
            return False
        if rminor < lminor:
            return True
        if rpatch > lpatch:
            print('Local version is older than remote version! Skipping.')
            return False
        if rpatch < lpatch:
            return True
        raise RuntimeError('Dont know how i got here!')


def get_packages() -> list[Pkg]:
    cmd = ['colcon', 'list', '-t']
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE)
    lines = result.stdout.splitlines()
    pkgs = []
    for line in lines:
        name, path, _ = line.split('\t')
        path = os.path.join(WORKSPACE_DIR, path)
        pkgs.append(Pkg(name, path))

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
    pkgs = get_packages()
    # we do this only once. it is required because we are in a docker
    # environment and the sources list is deleted by convention
    run_apt_update()
    run_rosdep_update()
    for pkg in pkgs:
        print(f'\nProcessing {pkg.name}')
        if not pkg.requires_rebuild():
            continue
        install_dependencies(pkg)
        build_package(pkg)
        install_package(pkg)
        run_rosdep_update()
