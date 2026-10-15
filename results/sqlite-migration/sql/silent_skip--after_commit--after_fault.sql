BEGIN TRANSACTION;
CREATE TABLE bindings(binding_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE,
          state TEXT NOT NULL CHECK(state IN ('active','retired')), payload_json TEXT NOT NULL,
          FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
INSERT INTO "bindings" VALUES('01-valid','task-valid','active','{"assignment_id":"task-valid","delivery_evidence":"retryable","requester_evidence":"confirmed","state":"active","version":1}');
INSERT INTO "bindings" VALUES('05-unknown','task-unknown','active','{"assignment_id":"task-unknown","delivery_evidence":"retryable","requester_evidence":"unknown","state":"active","version":1}');
INSERT INTO "bindings" VALUES('06-terminal','task-terminal','retired','{"assignment_id":"task-terminal","delivery_evidence":"terminal","requester_evidence":"confirmed","state":"active","version":1}');
CREATE TABLE legacy_bindings(binding_id TEXT PRIMARY KEY, value_json TEXT NOT NULL);
INSERT INTO "legacy_bindings" VALUES('01-valid','{"assignment_id":"task-valid","delivery_evidence":"retryable","requester_evidence":"confirmed","state":"active","version":1}');
INSERT INTO "legacy_bindings" VALUES('02-missing','{"delivery_evidence":"retryable","requester_evidence":"confirmed","state":"active","version":1}');
INSERT INTO "legacy_bindings" VALUES('03-truncated','{"version":1,"assignment_id":');
INSERT INTO "legacy_bindings" VALUES('04-version','{"assignment_id":"task-version","delivery_evidence":"retryable","requester_evidence":"confirmed","state":"active","version":99}');
INSERT INTO "legacy_bindings" VALUES('05-unknown','{"assignment_id":"task-unknown","delivery_evidence":"retryable","requester_evidence":"unknown","state":"active","version":1}');
INSERT INTO "legacy_bindings" VALUES('06-terminal','{"assignment_id":"task-terminal","delivery_evidence":"terminal","requester_evidence":"confirmed","state":"active","version":1}');
CREATE TABLE migration_state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
          diagnostic_status TEXT NOT NULL, policy TEXT);
INSERT INTO "migration_state" VALUES(1,1,'clean','silent_skip');
CREATE TABLE obligations(task_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('accepted','runnable','blocked','done')),
          reason TEXT, FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
INSERT INTO "obligations" VALUES('task-valid','01-valid','runnable',NULL);
INSERT INTO "obligations" VALUES('task-missing','02-missing','accepted',NULL);
INSERT INTO "obligations" VALUES('task-truncated','03-truncated','accepted',NULL);
INSERT INTO "obligations" VALUES('task-version','04-version','accepted',NULL);
INSERT INTO "obligations" VALUES('task-unknown','05-unknown','blocked','unknown_requester_evidence');
INSERT INTO "obligations" VALUES('task-terminal','06-terminal','blocked','terminal_binding');
CREATE TABLE warnings(binding_id TEXT PRIMARY KEY, code TEXT NOT NULL,
          original_sha256 TEXT NOT NULL, FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
COMMIT;
