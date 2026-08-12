#!/usr/bin/env python3
"""
Script to ensure all users have unique job titles/designations.
Run this once to populate users without jobs and fix missing designations.

Usage: python scripts/ensure_unique_jobs.py
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role

# Common job titles based on roles
ROLE_BASED_JOBS = {
    'system_administrator': [
        'System Administrator',
        'System Manager',
        'IT Director',
        'Systems Officer',
        'Infrastructure Manager'
    ],
    'accounting_officer': [
        'Accounting Officer',
        'Finance Manager',
        'Accountant',
        'Financial Controller',
        'Treasurer'
    ],
    'procurement_oversight': [
        'Procurement Oversight Officer',
        'Chief Procurement Officer',
        'Procurement Director',
        'Procurement Manager',
        'Procurement Specialist'
    ],
    'procurement_unit': [
        'Procurement Specialist',
        'Procurement Officer',
        'Procurement Coordinator',
        'Tender Officer',
        'Procurement Administrator'
    ],
    'user_department': [
        'Department Officer',
        'Departmental Representative',
        'User Department Staff',
        'Department Coordinator',
        'Administrative Officer'
    ],
    'committee_chair': [
        'Committee Chair',
        'Evaluation Committee Chairperson',
        'Committee Lead',
        'Chairperson',
        'Committee Director'
    ],
    'committee_secretary': [
        'Committee Secretary',
        'Committee Administrator',
        'Committee Coordinator',
        'Administrative Secretary',
        'Committee Support Officer'
    ],
    'evaluator': [
        'Evaluator',
        'Technical Evaluator',
        'Bid Evaluator',
        'Evaluation Officer',
        'Assessment Specialist'
    ],
    'opening_panel': [
        'Bid Opening Panel Member',
        'Opening Panel Officer',
        'Opening Committee Member',
        'Tender Opening Official',
        'Bid Verification Officer'
    ],
    'bidder': [
        'Bidder',
        'Bid Manager',
        'Tender Manager',
        'Business Development Officer',
        'Commercial Manager',
        'Sales Manager',
        'Project Manager',
        'Business Manager'
    ]
}

DEFAULT_JOBS = {
    'system_administrator': 'System Administrator',
    'accounting_officer': 'Accounting Officer',
    'procurement_oversight': 'Procurement Oversight Officer',
    'procurement_unit': 'Procurement Officer',
    'user_department': 'Department Officer',
    'committee_chair': 'Committee Chair',
    'committee_secretary': 'Committee Secretary',
    'evaluator': 'Evaluator',
    'opening_panel': 'Bid Opening Panel Member',
    'bidder': 'Bidder'
}


def ensure_unique_jobs():
    """Ensure all users have unique job titles."""
    app = create_app()
    
    with app.app_context():
        # Fetch all users
        users = User.query.all()
        
        if not users:
            print("No users found in database.")
            return
        
        print(f"Processing {len(users)} users...\n")
        
        job_counter = {}  # Track job title usage
        updates_made = 0
        
        for user in users:
            role = user.role
            role_code = role.code if role else 'user_department'
            
            # Check if user has designation
            if not user.designation or user.designation.strip() == '' or user.designation == 'New User':
                # Assign default job based on role
                base_job = DEFAULT_JOBS.get(role_code, 'Staff Member')
                
                # Make it unique if needed
                if base_job in job_counter:
                    job_counter[base_job] += 1
                    # For duplicate roles, add counter suffix
                    if job_counter[base_job] > 1:
                        user.designation = f"{base_job} {job_counter[base_job]}"
                    else:
                        user.designation = base_job
                else:
                    job_counter[base_job] = 1
                    user.designation = base_job
                
                print(f"✓ {user.username} ({user.email}): assigned '{user.designation}'")
                updates_made += 1
            else:
                # User already has a designation - track it
                job = user.designation
                if job in job_counter:
                    job_counter[job] += 1
                else:
                    job_counter[job] = 1
                
                print(f"  {user.username} ({user.email}): '{user.designation}' ✓ (existing)")
        
        # Commit changes
        if updates_made > 0:
            db.session.commit()
            print(f"\n✓ Successfully updated {updates_made} users with job titles.")
        else:
            print(f"\n✓ All users already have job titles.")
        
        # Summary
        print(f"\nJob Title Summary:")
        print(f"  Total unique job titles: {len(job_counter)}")
        for job, count in sorted(job_counter.items(), key=lambda x: x[1], reverse=True):
            print(f"    - {job}: {count} user(s)")


if __name__ == '__main__':
    ensure_unique_jobs()
