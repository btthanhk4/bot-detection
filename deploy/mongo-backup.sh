#!/bin/sh
# Daily dump of every MongoDB database used by SilkMoon and DATACAT; keeps 14 days.
# Install on the server:
#   install -m 700 deploy/mongo-backup.sh /usr/local/bin/mongo-backup.sh
#   ( crontab -l 2>/dev/null; echo "30 19 * * * /usr/local/bin/mongo-backup.sh >> /var/log/mongo-backup.log 2>&1" ) | crontab -
# Restore: docker exec -i silkmoon-mongodb mongorestore --archive --gzip < /var/backups/mongo/<file>
set -eu
DIR=/var/backups/mongo
mkdir -p "$DIR"
STAMP=$(date +%Y%m%d-%H%M)
docker exec silkmoon-mongodb mongodump --quiet --archive --gzip > "$DIR/mongo-$STAMP.archive.gz.part"
mv "$DIR/mongo-$STAMP.archive.gz.part" "$DIR/mongo-$STAMP.archive.gz"
find "$DIR" -name "mongo-*.archive.gz" -mtime +14 -delete
