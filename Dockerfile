ARG ROS_DISTRO
FROM ros:${ROS_DISTRO}
ARG ROS_DISTRO

RUN mkdir -p /ros2/src

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y \
    python3-bloom \
    python3-rosdep \
    python3-pip \
    fakeroot \
    debhelper \
    dh-python \
    && echo "deb [ signed-by=/etc/apt/keyrings/hippocampus-robotics.asc ] https://repositories.hippocampus-robotics.net/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" > /etc/apt/sources.list.d/hippocampus.list \
    && curl https://repositories.hippocampus-robotics.net/hippo-archive.key -o /etc/apt/keyrings/hippocampus-robotics.asc \
    && rm /etc/ros/rosdep/sources.list.d/20-default.list \
    && rosdep init \
    && echo "yaml https://raw.githubusercontent.com/HippoCampusRobotics/hippo_common/main/rosdep-${ROS_DISTRO}.yaml" > /etc/ros/rosdep/sources.list.d/50-hippocampus-packages.list \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*
ENV TERM=xterm-256color

WORKDIR /ros2

COPY ./src /ros2/src
COPY ./scripts /scripts
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["python3",  "-u", "/scripts/build_everything.py"]
CMD ["/bin/bash"]

