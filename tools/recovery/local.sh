#!/bin/sh
set -eu

fail() { echo "$*" >&2; exit 1; }
usage() { echo "$*" >&2; exit 2; }
valid_project() {
  case "$1" in csi-benchmark-[a-z0-9]*|csi-recovery-[a-z0-9]*) [ "${#1}" -le 63 ] ;; *) return 1 ;; esac
}
private_file() {
  [ "${1#/}" != "$1" ] || fail 'Use an absolute private backup path.'
  parent=$(cd "$(dirname "$1")" && pwd -P) || fail 'Backup directory does not exist.'
  case "$parent" in "$PWD"|"$PWD"/*) fail 'Backups must stay outside Git.' ;; esac
  backup="$parent/$(basename "$1")"
}

case "${1:-}" in
  backup)
    [ "$#" -eq 3 ] && valid_project "$2" || usage 'Usage: ./dev recovery:backup <csi-benchmark-or-recovery-project> <absolute-private-file>'
    private_file "$3"
    [ ! -e "$backup" ] || fail 'Backup file already exists.'
    umask 077
    temporary=$(mktemp "$backup.partial.XXXXXX")
    trap 'rm -f "$temporary"' EXIT HUP INT TERM
    if ! docker compose -p "$2" exec -T db sh -c \
      'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -U customer_insights -d customer_insights' > "$temporary"; then
      fail 'Backup failed; partial file removed.'
    fi
    [ -s "$temporary" ] || fail 'Backup was empty.'
    mv "$temporary" "$backup"
    trap - EXIT HUP INT TERM
    echo "Private backup created: $backup"
    ;;
  restore)
    [ "$#" -eq 4 ] && valid_project "$3" && [ "$3" = "$4" ] || usage 'Usage: ./dev recovery:restore <absolute-private-file> <new-csi-recovery-project> <same-name-to-approve>'
    case "$3" in csi-recovery-*) ;; *) usage 'Usage: restore target must be a new csi-recovery project.' ;; esac
    private_file "$2"
    [ -s "$backup" ] || fail 'Backup file is missing or empty.'
    docker volume inspect "${3}_postgres-data" >/dev/null 2>&1 && fail 'Restore target volume already exists.'
    [ -z "$(docker ps -a -q --filter "label=com.docker.compose.project=$3")" ] || fail 'Restore target containers already exist.'
    docker compose -p "$3" up -d --wait db
    if ! docker compose -p "$3" exec -T db sh -c \
      'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --no-owner --no-acl --single-transaction -U customer_insights -d customer_insights' < "$backup"; then
      fail 'Restore failed; target remains isolated for inspection.'
    fi
    docker compose -p "$3" exec -T db sh -c \
      'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -v ON_ERROR_STOP=1 -U customer_insights -d customer_insights' <<'SQL'
BEGIN;
DELETE FROM spring_session;
UPDATE dataset_instance SET instance_epoch = gen_random_uuid();
COMMIT;
SQL
    docker compose -p "$3" run --rm db-provision
    echo "Restored $3 with invalidated sessions and a new dataset epoch. Its API remains stopped."
    ;;
  *) usage 'Usage: ./dev recovery:backup|recovery:restore ...' ;;
esac
