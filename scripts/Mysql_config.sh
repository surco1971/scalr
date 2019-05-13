#!/bin/bash

# Install stuff that we will use later on
apt-get update
apt-get install -y bc mysql-utilities

# Reset the mysql root password
service mysql stop
sleep 1

# Necessary on ubuntu 16
mkdir -p /var/run/mysqld
chown mysql:mysql /var/run/mysqld

mysqld_safe --skip-grant-tables &
sleep 3
# One of the statement below will fail depending on the mysql version, but that's ok.
cat > /root/reset.sql <<EOF
flush privileges;
UPDATE user SET password=PASSWORD('') where User='root';
ALTER USER 'root'@'localhost' IDENTIFIED BY '';
flush privileges;
EOF
mysql -u root -f -D mysql < /root/reset.sql
sleep 1
pkill mysqld
sleep 3
rm /root/reset.sql

# We dont want the next statements to be in the binlog
service mysql start
sleep 2

# Create mysql user with new password
# Note: to simplify the demo setup, we are using the root user without a password
# This is very unsafe and suitable only for short-lived demos or tests
# Do not use this script on a server where the mysql port (3306) is open on the internet
# In a real deployment, use a secret management tool to grant access to the application servers
mysql -e "uninstall plugin validate_password;"
mysql -e "CREATE USER 'root'@'%' IDENTIFIED BY '';"
mysql -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;"

# Add our configuration
SERVER_ID=$(echo "$RANDOM * $RANDOM" | bc)
echo "MySQL server-id: $SERVER_ID"

cat > /etc/mysql/app.cnf <<EOF
[mysqld]
bind-address = 0.0.0.0
log_bin = mysql-bin
log_slave_updates = true
server-id = $SERVER_ID
innodb_flush_log_at_trx_commit = 1
sync_binlog = 1
EOF

echo '!include /etc/mysql/app.cnf' >> /etc/mysql/my.cnf

rm /var/lib/mysql/auto.cnf

# Restart mysql
service mysql restart
