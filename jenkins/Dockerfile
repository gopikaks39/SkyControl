# Jenkins controller with the Docker CLI, so the SkyControl pipeline can build and run containers.
FROM docker:27-cli AS cli
FROM jenkins/jenkins:lts-jdk17
USER root
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
USER jenkins
