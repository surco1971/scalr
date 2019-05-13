#!/bin/bash
 
sudo apt-get update
 
sudo debconf-set-selections <<< 'mysql-server-5.7 mysql-server/root_password password root'
sudo debconf-set-selections <<< 'mysql-server-5.7 mysql-server/root_password_again password root'
sudo apt-get -y install mysql-server-5.7
