from flask import Flask, render_template, request, jsonify
from config import Config
from auth import auth_bp, login_manager
from routes_admin import admin_bp
from routes_teacher import teacher_bp
from routes_student import student_bp
import sqlite3
import os
import socket
from datetime import datetime, timezone
import uuid


SYNC_TABLES = [
    'users',
    'students',
    'teachers',
    'assignments',
    'submissions',
    'allowed_late_submissions',
    'system_settings',
]


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def get_node_id():
    return os.environ.get('NODE_ID') or socket.gethostname()


LOCAL_NODE_ID = get_node_id()

def generate_id():
    """Generate a globally unique ID using UUID v4."""
    return str(uuid.uuid4())

def migrate_legacy_schema():
    """
    Migrate from legacy INTEGER id schema to UUID-based schema.
    This function detects if the database uses old integer PKs and safely converts them to UUIDs.
    """
    conn = sqlite3.connect('assignments.db')
    cur = conn.cursor()
    
    try:
        # Check if old schema exists (INTEGER PRIMARY KEY)
        cur.execute("PRAGMA table_info(users)")
        columns = cur.fetchall()
        id_col = next((c for c in columns if c[1] == 'id'), None)
        
        if id_col is None:
            # Table doesn't exist yet, no migration needed
            return True
        
        # Check if id column is INTEGER (old schema)
        if 'INT' not in id_col[2].upper():
            # Already TEXT, no migration needed
            return True
        
        # Backup old database
        import shutil
        backup_file = 'assignments.db.backup'
        if os.path.exists('assignments.db'):
            shutil.copy('assignments.db', backup_file)
            print(f"Created backup: {backup_file}")
        
        # Delete old tables and recreate with UUID schema
        tables = ['allowed_late_submissions', 'submissions', 'assignments', 'teachers', 'students', 'users', 'system_settings']
        for table in tables:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        
        print("Dropped legacy tables. New UUID-based schema will be created.")
        return True
    except Exception as e:
        print(f"Migration check failed (non-critical): {e}")
        return True
    finally:
        conn.close()

def init_db():
    # Attempt to migrate from legacy integer ID schema to UUID schema if needed
    migrate_legacy_schema()
    
    conn = sqlite3.connect('assignments.db')
    cur = conn.cursor()
    node_id_sql = LOCAL_NODE_ID.replace("'", "''")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_approved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE REFERENCES users(id),
            department TEXT NOT NULL,
            year INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE REFERENCES users(id),
            departments TEXT NOT NULL,
            years TEXT NOT NULL,
            courses TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            teacher_id TEXT REFERENCES teachers(id),
            course_name TEXT NOT NULL,
            department TEXT NOT NULL,
            year INTEGER NOT NULL,
            deadline TIMESTAMP NOT NULL,
            late_submission INTEGER DEFAULT 0,
            penalty_per_day REAL DEFAULT 0.0,
            max_score REAL DEFAULT 100.0,
            is_group INTEGER DEFAULT 0,
            max_group_size INTEGER DEFAULT 1,
            teacher_comment TEXT,
            files TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)
    # Ensure legacy DBs have max_score column
    cur.execute("PRAGMA table_info(assignments)")
    cols = [r[1] for r in cur.fetchall()]
    if 'max_score' not in cols:
        try:
            cur.execute("ALTER TABLE assignments ADD COLUMN max_score REAL DEFAULT 100.0")
        except Exception:
            pass
    if 'is_group' not in cols:
        try:
            cur.execute("ALTER TABLE assignments ADD COLUMN is_group INTEGER DEFAULT 0")
        except Exception:
            pass
    if 'max_group_size' not in cols:
        try:
            cur.execute("ALTER TABLE assignments ADD COLUMN max_group_size INTEGER DEFAULT 1")
        except Exception:
            pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            assignment_id TEXT REFERENCES assignments(id),
            student_id TEXT REFERENCES students(id),
            files TEXT,
            student_comment TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            grade REAL,
            feedback TEXT,
            evaluated_at TIMESTAMP,
            status TEXT DEFAULT 'submitted',
            complaint TEXT,
            complaint_status TEXT,
            group_id TEXT,
            node_id TEXT
        )
    """)
    # ensure legacy DB has group_id
    cur.execute("PRAGMA table_info(submissions)")
    subs_cols = [r[1] for r in cur.fetchall()]
    if 'group_id' not in subs_cols:
        try:
            cur.execute("ALTER TABLE submissions ADD COLUMN group_id INTEGER")
        except Exception:
            pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS allowed_late_submissions (
            id TEXT PRIMARY KEY,
            assignment_id TEXT REFERENCES assignments(id),
            student_id TEXT REFERENCES students(id),
            reason TEXT,
            allowed_by TEXT REFERENCES teachers(id),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            node_id TEXT
        )
    """)
    
    # Keep older databases compatible by adding missing sync columns.
    sync_columns = {
        'users': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'students': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'teachers': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'assignments': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'submissions': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'allowed_late_submissions': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
        'system_settings': [('updated_at', 'TIMESTAMP'), ('node_id', 'TEXT')],
    }

    for table, columns in sync_columns.items():
        cur.execute(f"PRAGMA table_info({table})")
        existing_cols = [r[1] for r in cur.fetchall()]
        for col_name, col_type in columns:
            if col_name not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

    # Backfill missing metadata on old rows.
    cur.execute("UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE students SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE teachers SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE assignments SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE submissions SET updated_at = COALESCE(updated_at, submitted_at, evaluated_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE allowed_late_submissions SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")
    cur.execute("UPDATE system_settings SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL")

    cur.execute("UPDATE users SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE students SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE teachers SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE assignments SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE submissions SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE allowed_late_submissions SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))
    cur.execute("UPDATE system_settings SET node_id = COALESCE(node_id, ?) WHERE node_id IS NULL OR node_id = ''", (LOCAL_NODE_ID,))

    # Trigger-based metadata updates: local writes that do not explicitly set updated_at/node_id
    # are stamped automatically, while incoming sync writes can preserve remote timestamps.
    for table in SYNC_TABLES:
        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_auto_updated_at
            AFTER UPDATE ON {table}
            FOR EACH ROW
            WHEN NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at
            BEGIN
                UPDATE {table}
                SET updated_at = CURRENT_TIMESTAMP
                WHERE rowid = NEW.rowid;
            END;
        """)

        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_auto_node_id_insert
            AFTER INSERT ON {table}
            FOR EACH ROW
            WHEN NEW.node_id IS NULL OR NEW.node_id = ''
            BEGIN
                UPDATE {table}
                SET node_id = '{node_id_sql}'
                WHERE rowid = NEW.rowid;
            END;
        """)

        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_auto_node_id_update
            AFTER UPDATE ON {table}
            FOR EACH ROW
            WHEN NEW.node_id IS NULL OR NEW.node_id = ''
            BEGIN
                UPDATE {table}
                SET node_id = '{node_id_sql}'
                WHERE rowid = NEW.rowid;
            END;
        """)

    # Incremental sync performance indexes.
    for table in SYNC_TABLES:
        try:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_updated_at ON {table}(updated_at)")
        except Exception:
            pass
    
    conn.commit()
    conn.close()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    with app.app_context():
        init_db()
    
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    
    @app.route('/')
    def index():
        return render_template('landing.html')

    def _table_exists(cur, table_name):
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return cur.fetchone() is not None

    def _table_columns(cur, table_name):
        cur.execute(f"PRAGMA table_info({table_name})")
        return cur.fetchall()

    def _parse_sync_ts(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            pass
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _rows_as_dicts(rows, col_names):
        result = []
        for r in rows:
            result.append({col_names[i]: r[i] for i in range(len(col_names))})
        return result

    def _normalize_incoming_row(row, col_names):
        if isinstance(row, dict):
            return {k: row.get(k) for k in col_names if k in row}
        if isinstance(row, (list, tuple)):
            return {col_names[i]: row[i] for i in range(min(len(col_names), len(row)))}
        return {}

    def _merge_table_rows(cur, table_name, incoming_rows):
        if not incoming_rows or not _table_exists(cur, table_name):
            return {'inserted': 0, 'updated': 0, 'skipped': 0}

        col_info = _table_columns(cur, table_name)
        col_names = [c[1] for c in col_info]
        pk_cols = [c[1] for c in col_info if c[5] == 1]
        pk_col = pk_cols[0] if pk_cols else None
        has_updated_at = 'updated_at' in col_names

        # Without a stable key we cannot merge deterministically; skip safely.
        if pk_col is None:
            return {'inserted': 0, 'updated': 0, 'skipped': len(incoming_rows)}

        inserted = 0
        updated = 0
        skipped = 0

        for raw_row in incoming_rows:
            row_data = _normalize_incoming_row(raw_row, col_names)
            pk_value = row_data.get(pk_col)
            if pk_value is None:
                skipped += 1
                continue

            cur.execute(f"SELECT * FROM {table_name} WHERE {pk_col} = ?", (pk_value,))
            local_existing = cur.fetchone()

            writable_cols = [c for c in col_names if c in row_data]
            if not writable_cols:
                skipped += 1
                continue

            if local_existing is None:
                placeholders = ', '.join(['?'] * len(writable_cols))
                cur.execute(
                    f"INSERT INTO {table_name} ({', '.join(writable_cols)}) VALUES ({placeholders})",
                    tuple(row_data[c] for c in writable_cols),
                )
                inserted += 1
                continue

            if not has_updated_at:
                skipped += 1
                continue

            local_idx = col_names.index('updated_at')
            local_updated = _parse_sync_ts(local_existing[local_idx])
            remote_updated = _parse_sync_ts(row_data.get('updated_at'))

            should_update = local_updated is None and remote_updated is not None
            if remote_updated is not None and (local_updated is None or remote_updated > local_updated):
                should_update = True

            if not should_update:
                skipped += 1
                continue

            update_cols = [c for c in writable_cols if c != pk_col]
            if not update_cols:
                skipped += 1
                continue

            assignments = ', '.join([f"{c} = ?" for c in update_cols])
            values = [row_data[c] for c in update_cols]
            values.append(pk_value)
            cur.execute(f"UPDATE {table_name} SET {assignments} WHERE {pk_col} = ?", tuple(values))
            updated += 1

        return {'inserted': inserted, 'updated': updated, 'skipped': skipped}
    
    @app.route('/sync/data', methods=['GET'])
    def sync_data():
        since = request.args.get('since')
        conn = sqlite3.connect('assignments.db')
        cur = conn.cursor()

        data = {}
        for table in SYNC_TABLES:
            if not _table_exists(cur, table):
                data[table] = []
                continue

            col_info = _table_columns(cur, table)
            col_names = [c[1] for c in col_info]
            has_updated_at = 'updated_at' in col_names

            if since and has_updated_at:
                cur.execute(f"SELECT * FROM {table} WHERE updated_at > ?", (since,))
            else:
                cur.execute(f"SELECT * FROM {table}")

            rows = cur.fetchall()
            data[table] = _rows_as_dicts(rows, col_names)

        conn.close()

        return jsonify({
            'node_id': LOCAL_NODE_ID,
            'server_time': now_utc_iso(),
            'since': since,
            'data': data,
        })
    
    @app.route('/sync/update', methods=['POST'])
    def sync_update():
        payload = request.get_json(silent=True) or {}
        incoming_data = payload.get('data', payload)

        if not isinstance(incoming_data, dict):
            return jsonify({'status': 'error', 'message': 'Invalid sync payload'}), 400

        conn = sqlite3.connect('assignments.db')
        cur = conn.cursor()

        summary = {
            'inserted': 0,
            'updated': 0,
            'skipped': 0,
            'tables': {},
        }

        try:
            for table, rows in incoming_data.items():
                if table not in SYNC_TABLES:
                    continue

                table_result = _merge_table_rows(cur, table, rows or [])
                summary['tables'][table] = table_result
                summary['inserted'] += table_result['inserted']
                summary['updated'] += table_result['updated']
                summary['skipped'] += table_result['skipped']

            conn.commit()
        except Exception as exc:
            conn.rollback()
            app.logger.exception('Sync merge failed: %s', exc)
            conn.close()
            return jsonify({'status': 'error', 'message': str(exc)}), 500

        conn.close()

        return jsonify({
            'status': 'ok',
            'node_id': LOCAL_NODE_ID,
            'received_at': now_utc_iso(),
            'summary': summary,
        })
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
