#!/bin/bash
# Crash eagerly
set -o errexit
set -o nounset


# Set default configuration parameters

DEFAULT_DEPLOY_PATH=/opt/scalr/webapp
DEFAULT_APP_REPO=https://github.com/scalr-tutorials/3-tier-app.git
DEFAULT_APP_BRANCH=master
DEFAULT_PORT=8000


# Use configuration from the environment if provided
# Fall back to defaults if no configuration is provided
# Note: environment variables can be provided using Scalr Global Variables

: ${DEPLOY_PATH:="$DEFAULT_DEPLOY_PATH"}
: ${APP_REPO:="$DEFAULT_APP_REPO"}
: ${APP_BRANCH:="$DEFAULT_APP_BRANCH"}
: ${PORT:="$DEFAULT_PORT"}


# Generate the PID file name based on the app port

PID_FILE="/var/run/webapp.${PORT}.pid"


# Install system dependencies
# Check operating system first

if [ -f /etc/debian_version ]; then
  OS=debian
  apt-get update
  apt-get install -y git python-setuptools curl
elif [ -f /etc/redhat-release ]; then
  OS=redhat
  yum -y install git MySQL-python curl
else
    echo "Unsupported OS"
    exit 1
fi


# Instal python dependencies
# This is platform-independent

easy_install pip
pip install flask gunicorn PyMySQL


# If the app hasn't been deployed yet, create the path, and deploy the app
# If the app had been deployed before, update it

if [ ! -d "$DEPLOY_PATH" ]; then
  mkdir -p "${DEPLOY_PATH}"
  rm -r "${DEPLOY_PATH}"
  git clone "${APP_REPO}" "${DEPLOY_PATH}" && cd "${DEPLOY_PATH}"
else
  cd $DEPLOY_PATH
  git fetch
fi

git checkout -B "${APP_BRANCH}" "origin/${APP_BRANCH}"


# Reload the app if it's running, otherwise launch it.

kill -s HUP `cat $PID_FILE 2>/dev/null` || {
  gunicorn --chdir $DEPLOY_PATH/app --daemon --pid $PID_FILE --bind 0.0.0.0:$PORT \
  --access-logfile /var/log/webapp.access.log --error-logfile /var/log/webapp.error.log \
  web:application
}


# Give the app some time to come up, and check it is indeed running

sleep 5
curl --fail --head --location "http://127.0.0.1:$PORT"


# Exit with a success

echo "Started Webapp - listening on $PORT"

exit 0

