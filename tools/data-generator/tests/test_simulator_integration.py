"""Real PostgreSQL checks for the restricted operator lifecycle."""

import json
import os
import secrets
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from csi_data.policy import ROOT


def command(*args, env=None, input=None):
    return subprocess.run(
        args, cwd=ROOT, env=env, input=input, capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def simulator():
    project = "csi-sim-test-" + uuid.uuid4().hex[:10]
    env = os.environ.copy()
    env["SIMULATOR_DB_PASSWORD"] = secrets.token_hex(32)
    try:
        started = command(
            "./dev", "fixture", project, env={**env, "CSI_ISOLATED_TEST_DB": "1"}
        )
        assert started.returncode == 0, started.stderr
        merchant = owner_query(
            project,
            "INSERT INTO merchants(id,display_name,mcc,default_category_code) "
            "VALUES ('sim-test-merchant','Simulator merchant','5411','GROCERIES')",
        )
        assert merchant.returncode == 0, merchant.stderr
        provisioned = command(
            "./dev",
            "simulate:provision",
            project,
            project,
            "--fixture",
            env={**env, "CSI_ISOLATED_TEST_DB": "1"},
        )
        assert provisioned.returncode == 0, provisioned.stderr
        yield project, env
    finally:
        command(
            "docker",
            "compose",
            "-p",
            project,
            "down",
            "-v",
            "--remove-orphans",
            env=env,
        )


def owner_query(project, sql):
    return command(
        "docker",
        "compose",
        "-p",
        project,
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -A -t -v ON_ERROR_STOP=1 -U customer_insights -d customer_insights -c "$1"',
        "sh",
        sql,
    )


def state(project, sql):
    result = owner_query(project, sql)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def simulate(target, operation, key, *fields):
    project, env = target
    return command(
        "./dev",
        "simulate",
        project,
        project,
        operation,
        key,
        *map(str, fields),
        env=env,
    )


def outcome(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def posted_balance(project, account="f01-everyday"):
    return state(
        project,
        "SELECT a.opening_balance_minor::numeric + COALESCE(("
        "SELECT sum(p.amount_minor::numeric) FROM posted_entries p "
        "WHERE p.account_id=a.id AND p.posted_at>=a.balance_anchor_at "
        "AND p.posted_at<'2026-11-01 00:00+02'),0) "
        f"FROM accounts a WHERE a.id='{account}'",
    )


def test_f15_exact_pending_post_cancel_and_replay(simulator):
    project, _ = simulator
    identity = state(
        project, "SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance"
    )
    before_revision = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f15'")
    )
    assert posted_balance(project, "f15-everyday") == "100000"
    assert (
        outcome(
            simulate(
                simulator,
                "pending",
                "f15pending",
                "f15-everyday",
                "sim-test-merchant",
                25000,
                "2026-10-30T10:00:00+02:00",
                "F15 purchase",
            )
        )["status"]
        == "PENDING"
    )
    assert posted_balance(project, "f15-everyday") == "100000"
    assert (
        outcome(
            simulate(
                simulator,
                "post",
                "f15post",
                "sim_auth_f15pending",
                24000,
                "2026-10-30T11:00:00+02:00",
            )
        )["status"]
        == "POSTED"
    )
    assert posted_balance(project, "f15-everyday") == "76000"
    assert (
        outcome(
            simulate(
                simulator,
                "post",
                "f15post",
                "sim_auth_f15pending",
                24000,
                "2026-10-30T11:00:00+02:00",
            )
        )["replayed"]
        is True
    )
    assert posted_balance(project, "f15-everyday") == "76000"
    assert (
        outcome(
            simulate(
                simulator,
                "pending",
                "f15cancelpending",
                "f15-everyday",
                "sim-test-merchant",
                10000,
                "2026-10-30T12:00:00+02:00",
                "F15 cancelled purchase",
            )
        )["status"]
        == "PENDING"
    )
    assert (
        outcome(
            simulate(
                simulator,
                "cancel",
                "f15cancel",
                "sim_auth_f15cancelpending",
                "2026-10-30T13:00:00+02:00",
            )
        )["status"]
        == "CANCELLED"
    )
    assert posted_balance(project, "f15-everyday") == "76000"
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f15'"
    ) == str(before_revision + 4)
    assert (
        state(
            project,
            "SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance",
        )
        == identity
    )


def test_pending_post_replay_and_exact_money(simulator):
    project, _ = simulator
    before = state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    )
    identity = state(
        project, "SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance"
    )
    assert posted_balance(project) == "2215000"
    pending = simulate(
        simulator,
        "pending",
        "purchase250",
        "f01-everyday",
        "sim-test-merchant",
        25000,
        "2026-10-30T10:00:00+02:00",
        "Test purchase",
    )
    assert outcome(pending)["status"] == "PENDING"
    assert posted_balance(project) == "2215000"
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_purchase250'",
        )
        == "0"
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(int(before) + 1)
    assert (
        outcome(
            simulate(
                simulator,
                "pending",
                "purchase250",
                "f01-everyday",
                "sim-test-merchant",
                25000,
                "2026-10-30T10:00:00+02:00",
                "Test purchase",
            )
        )["replayed"]
        is True
    )
    posted = simulate(
        simulator,
        "post",
        "settle240",
        "sim_auth_purchase250",
        24000,
        "2026-10-30T11:00:00+02:00",
    )
    assert outcome(posted)["amount_minor"] == -24000
    assert posted_balance(project) == "2191000"
    assert (
        state(
            project,
            "SELECT a.authorized_amount_minor||'|'||a.lifecycle_status||'|'||p.amount_minor||'|'||p.category_code||'|'||p.classification_provenance FROM authorizations a JOIN posted_entries p ON p.authorization_id=a.id WHERE a.id='sim_auth_purchase250'",
        )
        == "25000|POSTED|-24000|GROCERIES|MERCHANT"
    )
    assert (
        outcome(
            simulate(
                simulator,
                "post",
                "settle240",
                "sim_auth_purchase250",
                24000,
                "2026-10-30T11:00:00+02:00",
            )
        )["replayed"]
        is True
    )
    assert posted_balance(project) == "2191000"
    assert (
        state(
            project,
            "SELECT count(*)||'|'||sum(amount_minor) FROM posted_entries WHERE authorization_id='sim_auth_purchase250'",
        )
        == "1|-24000"
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(int(before) + 2)
    assert (
        state(
            project,
            "SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance",
        )
        == identity
    )
    assert (
        simulate(
            simulator,
            "post",
            "otherpost",
            "sim_auth_purchase250",
            24000,
            "2026-10-30T11:00:00+02:00",
        ).returncode
        != 0
    )
    assert (
        simulate(
            simulator,
            "cancel",
            "othercancel",
            "sim_auth_purchase250",
            "2026-10-30T12:00:00+02:00",
        ).returncode
        != 0
    )


def test_cancel_conflict_and_revision(simulator):
    project, _ = simulator
    before_balance = posted_balance(project)
    outcome(
        simulate(
            simulator,
            "pending",
            "cancelme",
            "f01-everyday",
            "sim-test-merchant",
            4300,
            "2026-10-30T12:00:00+02:00",
            "Cancelled purchase",
        )
    )
    before = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
    )
    assert (
        outcome(
            simulate(
                simulator,
                "cancel",
                "cancelkey",
                "sim_auth_cancelme",
                "2026-10-30T12:30:00+02:00",
            )
        )["status"]
        == "CANCELLED"
    )
    assert (
        outcome(
            simulate(
                simulator,
                "cancel",
                "cancelkey",
                "sim_auth_cancelme",
                "2026-10-30T12:30:00+02:00",
            )
        )["replayed"]
        is True
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(before + 1)
    assert posted_balance(project) == before_balance
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_cancelme'",
        )
        == "0"
    )
    assert (
        simulate(
            simulator,
            "post",
            "latepost",
            "sim_auth_cancelme",
            4300,
            "2026-10-30T13:00:00+02:00",
        ).returncode
        != 0
    )
    assert (
        simulate(
            simulator,
            "cancel",
            "cancelkey",
            "sim_auth_unknown",
            "2026-10-30T12:30:00+02:00",
        ).returncode
        != 0
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM simulator_events WHERE event_id='sim:event:latepost'",
        )
        == "0"
    )


def test_concurrent_same_key_and_different_keys(simulator):
    project, _ = simulator
    outcome(
        simulate(
            simulator,
            "pending",
            "raceauth",
            "f01-everyday",
            "sim-test-merchant",
            25000,
            "2026-10-30T14:00:00+02:00",
            "Racing purchase",
        )
    )
    before = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = list(
            pool.map(
                lambda _: simulate(
                    simulator,
                    "post",
                    "racepost",
                    "sim_auth_raceauth",
                    24000,
                    "2026-10-30T15:00:00+02:00",
                ),
                range(2),
            )
        )
    assert sorted(outcome(call)["replayed"] for call in calls) == [False, True]
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(before + 1)
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_raceauth'",
        )
        == "1"
    )
    outcome(
        simulate(
            simulator,
            "pending",
            "raceauth2",
            "f01-everyday",
            "sim-test-merchant",
            25000,
            "2026-10-30T16:00:00+02:00",
            "Racing purchase 2",
        )
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = list(
            pool.map(
                lambda key: simulate(
                    simulator,
                    "post",
                    key,
                    "sim_auth_raceauth2",
                    24000,
                    "2026-10-30T17:00:00+02:00",
                ),
                ("racefirst", "racesecond"),
            )
        )
    assert sum(call.returncode == 0 for call in calls) == 1
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_raceauth2'",
        )
        == "1"
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM simulator_events WHERE event_id IN ('sim:event:racefirst','sim:event:racesecond')",
        )
        == "1"
    )


def test_invalid_input_and_role_denials(simulator):
    project, env = simulator
    assert (
        simulate(
            simulator,
            "pending",
            "invaliddate",
            "f01-everyday",
            "sim-test-merchant",
            10,
            "2026-11-01T10:00:00+02:00",
            "Outside window",
        ).returncode
        != 0
    )
    assert (
        simulate(
            simulator,
            "pending",
            "negative",
            "f01-everyday",
            "sim-test-merchant",
            -1,
            "2026-10-30T10:00:00+02:00",
            "Invalid amount",
        ).returncode
        != 0
    )
    assert (
        simulate(
            simulator,
            "pending",
            "missingaccount",
            "unknown",
            "sim-test-merchant",
            10,
            "2026-10-30T10:00:00+02:00",
            "Invalid account",
        ).returncode
        != 0
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM simulator_events WHERE event_id IN ('sim:event:invaliddate','sim:event:negative','sim:event:missingaccount')",
        )
        == "0"
    )
    for sql in (
        "SELECT password_hash FROM credentials",
        "SELECT * FROM spring_session",
        "UPDATE customers SET customer_revision=0",
        "DELETE FROM posted_entries",
        "CREATE TABLE intruder(id integer)",
        "UPDATE simulator_approval SET dataset_id='unapproved-live-data'",
        "DELETE FROM simulator_approval",
        "SELECT pg_read_file('/etc/passwd')",
    ):
        attempt = command(
            "docker",
            "compose",
            "-p",
            project,
            "--profile",
            "simulator",
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "db-sim",
            env=env,
            input=sql + ";\n",
        )
        assert attempt.returncode != 0, sql
    assert (
        state(
            project,
            "SELECT has_table_privilege('customer_insights_api','posted_entries','INSERT')||'|'||has_function_privilege('customer_insights_api','simulate_transaction(text,text,jsonb)','EXECUTE')",
        )
        == "false|false"
    )
    assert (
        state(
            project,
            "SELECT has_function_privilege('customer_insights_simulator','simulate_transaction(text,text,jsonb)','EXECUTE')",
        )
        == "t"
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) acl WHERE p.oid='simulate_transaction(text,text,jsonb)'::regprocedure AND acl.grantee=0 AND acl.privilege_type='EXECUTE'",
        )
        == "0"
    )


def test_cli_validation():
    assert (
        command(
            "python3",
            "tools/simulator/cli.py",
            "bad/project",
            "bad/project",
            "cancel",
            "key",
            "auth",
        ).returncode
        != 0
    )
    assert (
        command(
            "python3",
            "tools/simulator/cli.py",
            "valid-project",
            "different",
            "cancel",
            "key",
            "auth",
        ).returncode
        != 0
    )
    assert (
        command(
            "python3",
            "tools/simulator/cli.py",
            "valid-project",
            "valid-project",
            "pending",
            "key",
            "account",
            "merchant",
            "10",
            "2026-02-31T10:00:00+02:00",
            "Invalid day",
        ).returncode
        != 0
    )


def test_fixture_replay_preserves_simulator_state(simulator):
    project, env = simulator
    outcome(
        simulate(
            simulator,
            "pending",
            "replayauth",
            "f01-everyday",
            "sim-test-merchant",
            25000,
            "2026-10-30T10:00:00+02:00",
            "Replay preservation",
        )
    )
    outcome(
        simulate(
            simulator,
            "post",
            "replaypost",
            "sim_auth_replayauth",
            24000,
            "2026-10-30T11:00:00+02:00",
        )
    )
    before = state(
        project,
        "SELECT (SELECT customer_revision FROM customers WHERE id='fixture-f01')||'|'||"
        "(SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance)||'|'||"
        "(SELECT count(*) FROM simulator_events)||'|'||"
        "(SELECT count(*) FROM posted_entries WHERE id LIKE 'sim_entry_%')",
    )
    replay = command(
        "./dev", "fixture", project, env={**env, "CSI_ISOLATED_TEST_DB": "1"}
    )
    assert replay.returncode == 0, replay.stderr
    assert (
        state(
            project,
            "SELECT (SELECT customer_revision FROM customers WHERE id='fixture-f01')||'|'||"
            "(SELECT seed_content_hash||'|'||instance_epoch FROM dataset_instance)||'|'||"
            "(SELECT count(*) FROM simulator_events)||'|'||"
            "(SELECT count(*) FROM posted_entries WHERE id LIKE 'sim_entry_%')",
        )
        == before
    )
    assert (
        outcome(
            simulate(
                simulator,
                "post",
                "settle240",
                "sim_auth_purchase250",
                24000,
                "2026-10-30T11:00:00+02:00",
            )
        )["replayed"]
        is True
    )


def test_post_failure_rolls_back_transition_and_retry(simulator):
    project, _ = simulator
    outcome(
        simulate(
            simulator,
            "pending",
            "rollbackauth",
            "f01-everyday",
            "sim-test-merchant",
            25000,
            "2026-10-30T18:00:00+02:00",
            "Rollback purchase",
        )
    )
    before = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
    )
    assert (
        owner_query(
            project, "INSERT INTO source_events VALUES ('sim:entry:blockedpost')"
        ).returncode
        == 0
    )
    failure = simulate(
        simulator,
        "post",
        "blockedpost",
        "sim_auth_rollbackauth",
        24000,
        "2026-10-30T19:00:00+02:00",
    )
    assert failure.returncode != 0
    assert (
        state(
            project,
            "SELECT lifecycle_status FROM authorizations WHERE id='sim_auth_rollbackauth'",
        )
        == "PENDING"
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_rollbackauth'",
        )
        == "0"
    )
    assert (
        state(
            project,
            "SELECT count(*) FROM simulator_events WHERE event_id='sim:event:blockedpost'",
        )
        == "0"
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(before)
    assert (
        owner_query(
            project,
            "DELETE FROM source_events WHERE source_event_id='sim:entry:blockedpost'",
        ).returncode
        == 0
    )
    assert (
        outcome(
            simulate(
                simulator,
                "post",
                "blockedpost",
                "sim_auth_rollbackauth",
                24000,
                "2026-10-30T19:00:00+02:00",
            )
        )["replayed"]
        is False
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(before + 1)
    assert (
        state(
            project,
            "SELECT count(*) FROM source_events WHERE source_event_id IN ('sim:auth:rollbackauth','sim:entry:blockedpost')",
        )
        == "2"
    )


@pytest.fixture
def approval_target():
    project = "csi-sim-approval-" + uuid.uuid4().hex[:10]
    env = {**os.environ, "SIMULATOR_DB_PASSWORD": secrets.token_hex(32)}
    try:
        started = command(
            "./dev", "fixture", project, env={**env, "CSI_ISOLATED_TEST_DB": "1"}
        )
        assert started.returncode == 0, started.stderr
        assert (
            owner_query(
                project,
                "INSERT INTO merchants(id,display_name,mcc,default_category_code) VALUES ('sim-test-merchant','Simulator merchant','5411','GROCERIES')",
            ).returncode
            == 0
        )
        yield project, env
    finally:
        command(
            "docker",
            "compose",
            "-p",
            project,
            "down",
            "-v",
            "--remove-orphans",
            env=env,
        )


def approve_fixture(target):
    project, env = target
    return command(
        "./dev",
        "simulate:provision",
        project,
        project,
        "--fixture",
        env={**env, "CSI_ISOLATED_TEST_DB": "1"},
    )


def assert_no_mutation(project, event_key, revision):
    assert (
        state(
            project,
            f"SELECT count(*) FROM authorizations WHERE id='sim_auth_{event_key}'",
        )
        == "0"
    )
    assert (
        state(
            project,
            f"SELECT count(*) FROM posted_entries WHERE id='sim_entry_{event_key}'",
        )
        == "0"
    )
    assert (
        state(
            project,
            f"SELECT count(*) FROM simulator_events WHERE event_id='sim:event:{event_key}'",
        )
        == "0"
    )
    assert (
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
        == revision
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("dataset_id", "unapproved-live-data"),
        ("seed_content_hash", "wrong-seed-hash"),
    ],
)
def test_approval_rejects_altered_identity(approval_target, column, value):
    project, _ = approval_target
    original = state(project, f"SELECT {column} FROM dataset_instance")
    revision = state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    )
    assert (
        owner_query(
            project, f"UPDATE dataset_instance SET {column}='{value}'"
        ).returncode
        == 0
    )
    assert approve_fixture(approval_target).returncode != 0
    assert state(project, "SELECT count(*) FROM simulator_approval") == "0"
    assert (
        simulate(
            approval_target,
            "pending",
            "deniedapproval",
            "f01-everyday",
            "sim-test-merchant",
            1000,
            "2026-10-30T10:00:00+02:00",
            "Denied approval",
        ).returncode
        != 0
    )
    assert_no_mutation(project, "deniedapproval", revision)
    assert state(project, f"SELECT {column} FROM dataset_instance") == value
    assert (
        owner_query(
            project, f"UPDATE dataset_instance SET {column}='{original}'"
        ).returncode
        == 0
    )
    assert state(project, "SELECT count(*) FROM simulator_approval") == "0"


@pytest.mark.parametrize(
    "column,value",
    [
        ("dataset_id", "unapproved-live-data"),
        ("seed_content_hash", "wrong-seed-hash"),
        ("instance_epoch", "00000000-0000-0000-0000-000000000001"),
    ],
)
def test_mutation_rejects_identity_changed_after_approval(
    approval_target, column, value
):
    project, _ = approval_target
    assert approve_fixture(approval_target).returncode == 0
    original = state(project, f"SELECT {column} FROM dataset_instance")
    revision = state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    )
    assert (
        owner_query(
            project, f"UPDATE dataset_instance SET {column}='{value}'"
        ).returncode
        == 0
    )
    assert (
        simulate(
            approval_target,
            "pending",
            "changedidentity",
            "f01-everyday",
            "sim-test-merchant",
            1000,
            "2026-10-30T10:00:00+02:00",
            "Changed identity",
        ).returncode
        != 0
    )
    assert_no_mutation(project, "changedidentity", revision)
    assert state(project, "SELECT count(*) FROM simulator_approval") == "1"
    assert (
        owner_query(
            project, f"UPDATE dataset_instance SET {column}='{original}'"
        ).returncode
        == 0
    )
    assert (
        outcome(
            simulate(
                approval_target,
                "pending",
                "changedidentity",
                "f01-everyday",
                "sim-test-merchant",
                1000,
                "2026-10-30T10:00:00+02:00",
                "Changed identity",
            )
        )["replayed"]
        is False
    )


def test_cancel_explicit_time_boundaries_and_replay(simulator):
    project, _ = simulator
    outcome(
        simulate(
            simulator,
            "pending",
            "timedauth",
            "f01-everyday",
            "sim-test-merchant",
            5000,
            "2026-10-30T10:00:00+02:00",
            "Timed cancellation",
        )
    )
    revision = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
    )
    for key, fields in (
        ("missingcancel", ("sim_auth_timedauth",)),
        ("malformedcancel", ("sim_auth_timedauth", "2026-02-31T12:00:00+02:00")),
        ("earlycancel", ("sim_auth_timedauth", "2026-10-30T09:59:59+02:00")),
        ("latecancel", ("sim_auth_timedauth", "2026-11-01T00:00:00+02:00")),
    ):
        assert simulate(simulator, "cancel", key, *fields).returncode != 0
        assert (
            state(
                project,
                f"SELECT count(*) FROM simulator_events WHERE event_id='sim:event:{key}'",
            )
            == "0"
        )
        assert (
            state(
                project,
                "SELECT lifecycle_status FROM authorizations WHERE id='sim_auth_timedauth'",
            )
            == "PENDING"
        )
        assert state(
            project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
        ) == str(revision)
    when = "2026-10-31T23:59:59+02:00"
    result = outcome(
        simulate(simulator, "cancel", "timedcancel", "sim_auth_timedauth", when)
    )
    assert result["status"] == "CANCELLED" and result["cancelled_at"] == when
    assert (
        outcome(
            simulate(simulator, "cancel", "timedcancel", "sim_auth_timedauth", when)
        )["replayed"]
        is True
    )
    assert (
        simulate(
            simulator,
            "cancel",
            "timedcancel",
            "sim_auth_timedauth",
            "2026-10-31T23:59:58+02:00",
        ).returncode
        != 0
    )
    assert (
        state(
            project,
            "SELECT (payload->>'cancelled_at')||'|'||(result->>'cancelled_at') FROM simulator_events WHERE event_id='sim:event:timedcancel'",
        )
        == when + "|" + when
    )
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(revision + 1)
    assert (
        state(
            project,
            "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_timedauth'",
        )
        == "0"
    )


def test_post_cancel_race_has_one_winner(simulator):
    project, env = simulator
    outcome(
        simulate(
            simulator,
            "pending",
            "postcancelrace",
            "f01-everyday",
            "sim-test-merchant",
            25000,
            "2026-10-30T10:00:00+02:00",
            "Post cancel race",
        )
    )
    revision = int(
        state(project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'")
    )
    lock = subprocess.Popen(
        [
            "docker",
            "compose",
            "-p",
            project,
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -A -t -v ON_ERROR_STOP=1 -U customer_insights -d customer_insights',
        ],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert lock.stdin is not None and lock.stdout is not None
    lock.stdin.write(
        "BEGIN; SELECT id FROM authorizations WHERE id='sim_auth_postcancelrace' FOR UPDATE; SELECT 'LOCKED';\n"
    )
    lock.stdin.flush()
    for line in lock.stdout:
        if line.strip() == "LOCKED":
            break
    else:
        raise AssertionError("Could not lock the authorisation")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            post = pool.submit(
                simulate,
                simulator,
                "post",
                "racepostcancelpost",
                "sim_auth_postcancelrace",
                24000,
                "2026-10-30T11:00:00+02:00",
            )
            cancel = pool.submit(
                simulate,
                simulator,
                "cancel",
                "racepostcancelcancel",
                "sim_auth_postcancelrace",
                "2026-10-30T11:00:00+02:00",
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    blocked = int(
                        state(
                            project,
                            "SELECT count(*) FROM pg_stat_activity WHERE usename='customer_insights_simulator' AND wait_event_type='Lock'",
                        )
                    )
                    if blocked == 2:
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError(
                        "Both simulator connections did not reach the authorisation lock"
                    )
            finally:
                lock.stdin.write("COMMIT;\n")
                lock.stdin.close()
                assert lock.wait(timeout=5) == 0
            post_result, cancel_result = (
                post.result(timeout=15),
                cancel.result(timeout=15),
            )
    finally:
        if lock.poll() is None:
            if not lock.stdin.closed:
                lock.stdin.write("ROLLBACK;\n")
                lock.stdin.close()
            lock.wait(timeout=5)
    assert sum(r.returncode == 0 for r in (post_result, cancel_result)) == 1
    winner = "POSTED" if post_result.returncode == 0 else "CANCELLED"
    assert (
        state(
            project,
            "SELECT lifecycle_status FROM authorizations WHERE id='sim_auth_postcancelrace'",
        )
        == winner
    )
    assert state(
        project,
        "SELECT count(*) FROM posted_entries WHERE authorization_id='sim_auth_postcancelrace'",
    ) == ("1" if winner == "POSTED" else "0")
    assert state(
        project, "SELECT customer_revision FROM customers WHERE id='fixture-f01'"
    ) == str(revision + 1)
    assert (
        state(
            project,
            "SELECT count(*) FROM simulator_events WHERE event_id IN ('sim:event:racepostcancelpost','sim:event:racepostcancelcancel')",
        )
        == "1"
    )
    assert state(
        project,
        "SELECT operation||'|'||(result->>'status') FROM simulator_events WHERE event_id IN ('sim:event:racepostcancelpost','sim:event:racepostcancelcancel')",
    ) == ("post|POSTED" if winner == "POSTED" else "cancel|CANCELLED")
