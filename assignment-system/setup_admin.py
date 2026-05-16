#!/usr/bin/env python3
"""
Setup script to create default admin user after UUID migration.
Run this once to initialize the system with an admin account.
"""

import sqlite3
import uuid
from werkzeug.security import generate_password_hash

def setup_admin():
    """Create a default admin user."""
    
    conn = sqlite3.connect('assignments.db')
    cur = conn.cursor()
    
    # Check if admin already exists
    cur.execute("SELECT id FROM users WHERE role = 'admin'")
    admin_exists = cur.fetchone()
    
    if admin_exists:
        print("✓ Admin user already exists. No setup needed.")
        conn.close()
        return
    
    # Create default admin
    admin_id = str(uuid.uuid4())
    admin_email = "admin@system.com"
    admin_user_id = "ADMIN001"
    admin_password = "admin123"  # Default password - change after first login!
    
    password_hash = generate_password_hash(admin_password)
    
    try:
        cur.execute("""
            INSERT INTO users (id, user_id, first_name, last_name, email, password_hash, role, is_approved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (admin_id, admin_user_id, "Admin", "User", admin_email, password_hash, "admin", 1))
        
        conn.commit()
        
        print("\n" + "=" * 70)
        print("ADMIN USER CREATED SUCCESSFULLY")
        print("=" * 70)
        print(f"\nLogin credentials:")
        print(f"  Email: {admin_email}")
        print(f"  User ID: {admin_user_id}")
        print(f"  Password: {admin_password}")
        print(f"\n⚠️  IMPORTANT: Change this password immediately after first login!")
        print("=" * 70 + "\n")
        
    except Exception as e:
        print(f"✗ Error creating admin user: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    setup_admin()
