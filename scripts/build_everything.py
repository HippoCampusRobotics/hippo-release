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
        self.path = path
        self.local_deps = []

    def add_dependency(self, name: str):
        self.local_deps.append(name)


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
    subprocess.check_output(shlex.split(cmd))


def run_rosdep_update():
    cmd = 'rosdep update'
    subprocess.check_output(shlex.split(cmd))


def install_dependencies(pkg):
    cmd = f'rosdep install --from-paths {pkg.path} -y --ignore-src'
    result = subprocess.Popen(shlex.split(cmd), shell=False)
    print(result.communicate()[0])


def build_package(pkg: Pkg):
    print(f'Processing {pkg.name}')
    env = os.environ.copy()
    dir = pkg.path
    cmd = 'bloom-generate rosdebian'
    shell = True
    if not shell:
        cmd = shlex.split(cmd)
    result = subprocess.Popen(cmd, shell=shell, cwd=dir, env=env)
    result.wait()
    print('Starting build process')
    cmd = 'fakeroot debian/rules binary --max-parallel=4'
    if not shell:
        cmd = shlex.split(cmd)
    result = subprocess.Popen(cmd, shell=shell, cwd=dir, env=env)
    result.wait()
    print('Build process done')


def install_package(pkg: Pkg):
    name = pkg.name.replace('_', '-')
    list_file = pathlib.Path(f'/etc/ros/rosdep/sources.list.d/50-{name}.list')
    yaml_file = pathlib.Path(f'/tmp/{name}.yaml')
    with list_file.open('w', encoding='utf-8') as f:
        f.write(f'yaml file://{str(yaml_file)}')

    deb_name = f'ros-{ROS_DISTRO}-{name}'
    data = {pkg.name: {'ubuntu': [deb_name]}}
    with yaml_file.open('w', encoding='utf-8') as f:
        yaml.dump(data, f)

    pattern = f'{pkg.path}/../{deb_name}*.deb'
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
    for pkg in pkgs:
        run_rosdep_update()
        install_dependencies(pkg)
        build_package(pkg)
        install_package(pkg)
