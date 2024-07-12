#!/usr/bin/bash

set -e

PKGS="$@"

cp -R /src/* /ros2/src/

apt update
: $(rosdep update)
rosdep install --from-paths /ros2/src -y --ignore-src

for pkg in $PKGS; do
    echo "Processing $pkg"
    current_dir=$(pwd)
    cd "$pkg"
    export DEB_BUILD_OPTIONS="parallel=`nproc`"
    bloom-generate rosdebian
    fakeroot debian/rules binary
    cd "${current_dir}"
done

PKGS=$(find . -type f -name '*.deb')
for pkg in $PKGS; do
    mv "$pkg" /debs/
done

# PKGS=$(find . -type f -name '*.ddeb')
# for pkg in $PKGS; do
#     mv "$pkg" /debs/
# done
