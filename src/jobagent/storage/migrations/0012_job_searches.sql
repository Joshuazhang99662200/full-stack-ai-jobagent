BEGIN IMMEDIATE;

-- Every search the host ran, including the ones that found nothing new, so the
-- next plan can rotate terms and judge them by what they actually turned up.
CREATE TABLE job_searches (
    source TEXT NOT NULL,
    search_term TEXT NOT NULL,
    searched_at TEXT NOT NULL,
    results INTEGER NOT NULL CHECK (results >= 0),
    new INTEGER NOT NULL CHECK (new >= 0),
    PRIMARY KEY (source, search_term, searched_at)
);

PRAGMA user_version = 12;

COMMIT;
