# cas_app/management/commands/seed_cas.py
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.utils import timezone

from cas_app.models import (
    Office, Case, CaseStatusHistory, CaseFeedback,
    Transfer, Assignment, RoleHierarchy,
)

User = get_user_model()

# Main roles for the system - Only these 5 roles are allowed
ROLES = [
    "Citizen",
    "Focal Person",
    "Director",
    "Mayor Office",
    "Admin",
]


def _unique_permissions(perms):
    """Return a sorted list of unique permission codenames."""
    return sorted(set(perms))


CITIZEN_PERMISSIONS = _unique_permissions(
    [
        "view_case",
        "add_case",
        "change_case",
        "view_casefeedback",
        "add_casefeedback",
        "view_casestatushistory",
        "view_transfer",
        "view_assignment",
        "view_office",
        "view_announcement",
    ]
)

FOCAL_CORE_PERMISSIONS = _unique_permissions(
    CITIZEN_PERMISSIONS
    + [
        "view_all_cases",
        "delete_case",
        "change_casefeedback",
        "delete_casefeedback",
        "add_assignment",
        "change_assignment",
        "delete_assignment",
        "add_transfer",
        "change_transfer",
        "delete_transfer",
        "add_announcement",
        "change_announcement",
    ]
)

MAYOR_OFFICE_PERMISSIONS = _unique_permissions(
    CITIZEN_PERMISSIONS
    + [
        "view_all_cases",
        "change_case",
        "view_assignment",
        "view_transfer",
        "change_transfer",
        "view_announcement",
        "change_announcement",
    ]
)

DIRECTOR_PERMISSIONS = _unique_permissions(
    FOCAL_CORE_PERMISSIONS
    + [
        "view_user",
        "add_user",
        "change_user",
        "delete_user",
        "view_group",
        "change_group",
        "view_office",
        "add_office",
        "change_office",
        "delete_office",
        "delete_announcement",
]
)

# Mayor Office permissions are already defined above
# Note: Mayor Office does not have group management permissions

# Admin gets ALL permissions - will be set dynamically in _assign_role_permissions
ADMIN_PERMISSIONS = []  # Placeholder, will be populated with all permissions

ROLE_PERMISSION_MATRIX = {
    "Citizen": CITIZEN_PERMISSIONS,
    "Focal Person": FOCAL_CORE_PERMISSIONS,
    "Director": DIRECTOR_PERMISSIONS,
    "Mayor Office": MAYOR_OFFICE_PERMISSIONS,
    "Admin": ADMIN_PERMISSIONS,  # Will be set to all permissions dynamically
}

PASSWORD = "Passw0rd!"

def uniq(n: int) -> str:
    """Return a zero-padded numeric string for uniqueness."""
    return f"{n:03d}"

class Command(BaseCommand):
    help = "Seed CAS demo data: groups, users, offices, cases, history, feedback, transfers, assignments. Always clears database before seeding."

    @transaction.atomic
    def handle(self, *args, **options):
        # Always clear database before seeding
        self.stdout.write(self.style.WARNING("Clearing existing seed data..."))
        
        # Clear all related data
        Assignment.objects.all().delete()
        Transfer.objects.all().delete()
        CaseFeedback.objects.all().delete()
        CaseStatusHistory.objects.all().delete()
        Case.objects.all().delete()
        Office.objects.all().delete()
        RoleHierarchy.objects.all().delete()
        
        # Remove users that match our seed pattern (avoid deleting real users)
        for u in User.objects.filter(email__endswith="@seed.local"):
            u.delete()
        
        # Remove admin user if it exists
        try:
            admin_user = User.objects.get(username="admin", email="admin@cas.local")
            admin_user.delete()
        except User.DoesNotExist:
            pass
        
        # Delete all groups that are NOT in our allowed roles list
        allowed_role_names = set(ROLES)
        all_groups = Group.objects.all()
        for group in all_groups:
            if group.name not in allowed_role_names:
                self.stdout.write(self.style.WARNING(f"Deleting unauthorized group: {group.name}"))
                group.delete()
        
        self.stdout.write(self.style.SUCCESS("Database cleared successfully."))

        self._ensure_groups()
        self._ensure_role_hierarchy()
        # Ensure admin is created AFTER groups are created
        admin = self._ensure_admin()

        users_by_group = self._seed_users_per_group()
        citizens = users_by_group["Citizen"]
        staff_users = [u for g, lst in users_by_group.items() if g != "Citizen" for u in lst]

        offices = self._seed_offices()
        cases = self._seed_cases(citizens=citizens, offices=offices, added_by=admin or random.choice(staff_users or citizens))
        self._seed_status_history(cases)
        self._seed_feedback(cases, citizens)
        self._seed_transfers(cases, offices)
        self._seed_assignments(cases, staff_users or citizens)

        self.stdout.write(self.style.SUCCESS("✅ Seeding complete."))

    # ---------- helpers ----------
    def _ensure_groups(self):
        """Create groups for all roles and assign permissions."""
        groups = {}
        # Create groups for all roles defined in ROLE_PERMISSION_MATRIX
        for name in ROLE_PERMISSION_MATRIX.keys():
            group, created = Group.objects.get_or_create(name=name)
            groups[name] = group
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created group: {name}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Group '{name}' already exists."))
        self.stdout.write(self.style.SUCCESS(f"Groups ensured ({len(groups)} groups)."))
        self._assign_role_permissions(groups)

    def _assign_role_permissions(self, groups: dict):
        """Attach predefined permission sets to each role-based group."""
        # For Admin role, assign ALL permissions
        all_permissions = list(Permission.objects.all())
        admin_group = groups.get("Admin")
        if admin_group:
            admin_group.permissions.set(all_permissions)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Permissions assigned to 'Admin' ({len(all_permissions)} permissions - ALL)."
                )
            )
        
        # For other roles, use predefined permission sets
        all_codes = {
            code for codes in ROLE_PERMISSION_MATRIX.values() 
            for code in codes if codes  # Skip empty Admin list
        }
        perms = Permission.objects.filter(codename__in=all_codes)
        perms_by_code = {perm.codename: perm for perm in perms}

        missing = sorted(all_codes - set(perms_by_code.keys()))
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  Missing permissions (check model migrations): {', '.join(missing)}"
                )
            )

        for role, codes in ROLE_PERMISSION_MATRIX.items():
            if role == "Admin":
                continue  # Already handled above
            group = groups.get(role) or Group.objects.get(name=role)
            assigned = [perms_by_code[code] for code in codes if code in perms_by_code]
            group.permissions.set(assigned)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Permissions assigned to '{role}' ({len(assigned)} permissions)."
                )
            )

    def _ensure_role_hierarchy(self):
        """Create role hierarchy configuration for dynamic transfer system."""
        # Define hierarchy: Citizen (1) -> Focal Person (2) -> Director (3) -> Mayor Office (4) -> Admin (5)
        hierarchy_config = {
            "Citizen": {
                "level": 1,
                "can_transfer_to": [],  # Citizens cannot transfer
                "can_assign": False,
                "can_change_status": False,
            },
            "Focal Person": {
                "level": 2,
                "can_transfer_to": ["Director"],  # Can transfer to Director
                "can_assign": True,
                "can_change_status": True,
            },
            "Director": {
                "level": 3,
                "can_transfer_to": ["Mayor Office"],  # Can transfer to Mayor Office
                "can_assign": True,
                "can_change_status": True,
            },
            "Mayor Office": {
                "level": 4,
                "can_transfer_to": [],  # Top level, cannot transfer further
                "can_assign": True,
                "can_change_status": True,
            },
            "Admin": {
                "level": 5,
                "can_transfer_to": [],  # Admin can manage everything but doesn't transfer cases
                "can_assign": True,
                "can_change_status": True,
            },
        }

        for role_name, config in hierarchy_config.items():
            try:
                group = Group.objects.get(name=role_name)
            except Group.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Group '{role_name}' not found. Skipping hierarchy setup."))
                continue

            hierarchy, created = RoleHierarchy.objects.get_or_create(
                role=group,
                defaults={
                    "hierarchy_level": config["level"],
                    "can_assign": config["can_assign"],
                    "can_change_status": config["can_change_status"],
                }
            )
            
            if not created:
                # Update existing hierarchy
                hierarchy.hierarchy_level = config["level"]
                hierarchy.can_assign = config["can_assign"]
                hierarchy.can_change_status = config["can_change_status"]
                hierarchy.save()

            # Set transfer targets
            transfer_targets = []
            for target_role_name in config["can_transfer_to"]:
                try:
                    target_group = Group.objects.get(name=target_role_name)
                    transfer_targets.append(target_group)
                except Group.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"Target role '{target_role_name}' not found."))
            
            hierarchy.can_transfer_to.set(transfer_targets)
            
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created hierarchy for '{role_name}' (Level {config['level']})"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Updated hierarchy for '{role_name}' (Level {config['level']})"))

    def _ensure_admin(self):
        """Create Admin user with Admin role (not superuser, uses group permissions)."""
        admin_email = "admin@cas.local"
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": admin_email,
                "first_name": "System",
                "last_name": "Admin",
                "national_id": "99-ADMIN-000",
                "phone_number": "+251900000000",
                "is_staff": False,  # Not staff, uses group permissions
                "is_superuser": False,  # Not superuser, uses group permissions
            },
        )
        if created:
            admin.set_password(PASSWORD)
            admin.save()
            self.stdout.write(self.style.SUCCESS(f"Admin user created (admin@cas.local / {PASSWORD})"))
        else:
            # Update password if user exists
            admin.set_password(PASSWORD)
            admin.save()
            self.stdout.write(self.style.SUCCESS(f"Admin user updated (admin@cas.local / {PASSWORD})"))
        
        # Always assign Admin group (even if user already exists)
        try:
            admin_group = Group.objects.get(name="Admin")
            # Clear existing groups and set only Admin group
            admin.groups.clear()
            admin.groups.add(admin_group)
            self.stdout.write(self.style.SUCCESS(f"Admin group assigned to admin user."))
        except Group.DoesNotExist:
            self.stdout.write(self.style.WARNING("Admin group not found. Run _ensure_groups first."))
        
        return admin

    def _seed_users_per_group(self):
        """
        Create 7 users per role (28 users for 4 roles: Citizen, Focal Person, Director, Mayor Office).
        Admin user is created separately in _ensure_admin, so we skip Admin here.
        Citizen users will be used as 'citizens' for cases.
        Each user gets assigned to their role's group with appropriate permissions.
        """
        users_by_group = {}
        base_counter = 1

        # Seed users for each role in ROLE_PERMISSION_MATRIX (except Admin, which is created separately)
        for role in ROLE_PERMISSION_MATRIX.keys():
            if role == "Admin":
                continue  # Admin user is created separately in _ensure_admin
            try:
                grp = Group.objects.get(name=role)
            except Group.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Group '{role}' not found. Skipping user creation."))
                continue

            bucket = []
            for i in range(1, 8):  # 1..7 users per role
                suffix = uniq(base_counter)
                # Generate username: handle multi-word roles like "Focal Person" -> "focalperson"
                role_prefix = role.replace(" ", "").replace("-", "").lower()
                username = f"{role_prefix}_{suffix}"
                email = f"{username}@seed.local"
                # National ID with role abbreviation
                role_abbr = "".join([w[0] for w in role.split()[:2]]).upper()[:3]
                nat_id = f"ID-{suffix}-{role_abbr}"
                phone = f"+2519{random.randint(10,99)}{random.randint(1000000,9999999)}"

                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": email,
                        "first_name": role.split()[0],
                        "last_name": f"User{suffix}",
                        "national_id": nat_id,
                        "phone_number": phone,
                        "status": "active",
                    },
                )
                if created:
                    user.set_password(PASSWORD)
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f"  Created user: {username} ({role})"))
                else:
                    self.stdout.write(self.style.WARNING(f"  User {username} already exists, updating group membership."))
                
                # Ensure group membership (users inherit permissions from their group)
                user.groups.set([grp])
                bucket.append(user)
                base_counter += 1
            users_by_group[role] = bucket
            self.stdout.write(self.style.SUCCESS(f"✓ Seeded {len(bucket)} users for '{role}' role."))

        total_users = sum(len(users) for users in users_by_group.values())
        self.stdout.write(self.style.SUCCESS(f"✅ Total users seeded: {total_users} across {len(users_by_group)} roles."))
        return users_by_group

    def _seed_offices(self):
        names = [
            "Kebele Office A",
            "Kebele Office B",
            "Wereda Office A",
            "Wereda Office B",
            "Sector Office A",
            "Directorate Office",
            "President Office",
        ]
        offices = []
        for name in names:
            office, _ = Office.objects.get_or_create(name=name)
            offices.append(office)
        self.stdout.write(self.style.SUCCESS("7 Offices seeded."))
        return offices

    def _seed_cases(self, citizens, offices, added_by):
        """
        Create 7 cases using random citizens and offices.
        Mix of statuses and priorities.
        """
        titles = [
            "Service Delay Complaint",
            "Water Supply Issue",
            "ID Processing Complaint",
            "Tax Clarification Request",
            "Permit Appeal",
            "Road Maintenance Complaint",
            "Administrative Decision Appeal",
        ]
        descriptions = [
            "Detail about the reported issue with relevant references.",
            "Citizen reported recurring problem affecting services.",
            "Follow-up needed with respective office focal person.",
            "Citizen requests clarification and faster resolution.",
            "Escalated to upper office for review and action.",
            "On-site assessment might be required.",
            "Subject to leadership final review.",
        ]
        categories = ["complaint", "appeal", "other"]
        channels = ["web", "walk_in", "phone"]
        priorities = ["low", "medium", "high", "urgent"]
        statuses = ["pending", "investigation", "resolved", "rejected", "closed"]

        cases = []
        now = timezone.now()
        for idx in range(7):
            citizen = random.choice(citizens)
            office = random.choice(offices)
            title = titles[idx]
            desc = descriptions[idx]
            category_id = random.choice(categories)
            channel = random.choice(channels)
            priority = random.choice(priorities)
            status = random.choice(statuses)

            case = Case.objects.create(
                citizen_id=citizen,
                office_id=office,
                title=title,
                description=desc,
                category_id=category_id,
                channel=channel,
                priority=priority,
                status=status,
                added_by=added_by,
                created_at=now - timedelta(days=random.randint(0, 20)),
            )
            cases.append(case)

        self.stdout.write(self.style.SUCCESS("7 Cases seeded."))
        return cases

    def _seed_status_history(self, cases):
        """
        Create at least one status history row per case (current status).
        """
        for case in cases:
            CaseStatusHistory.objects.create(
                case=case,
                status=case.status,
                changed_by=case.added_by,
            )
        self.stdout.write(self.style.SUCCESS("Case status history seeded."))

    def _seed_feedback(self, cases, citizens):
        """
        Create 7 feedback items. Ensure the target case is closed; if not, set to closed first.
        """
        targets = random.sample(cases, k=min(7, len(cases)))
        for case in targets:
            if case.status != "closed":
                case.status = "closed"
                case.save(update_fields=["status"])
                CaseStatusHistory.objects.create(case=case, status="closed", changed_by=case.added_by)

            owner = case.citizen_id
            rating = random.randint(3, 5)
            comment = random.choice([
                "Satisfied with the resolution.",
                "Resolution acceptable.",
                "Thanks for the prompt response.",
                "Communication could be better, but resolved.",
                "Appreciate the support.",
            ])
            # unique (case, created_by)
            CaseFeedback.objects.get_or_create(
                case=case,
                created_by=owner,
                defaults={"rating": rating, "comment": comment},
            )
        self.stdout.write(self.style.SUCCESS("7 Feedbacks seeded."))

    def _seed_transfers(self, cases, offices):
        """
        Create 7 transfers, updating the case office to the new office.
        """
        for _ in range(7):
            case = random.choice(cases)
            from_office = case.office_id or random.choice(offices)
            to_office = random.choice([o for o in offices if o.id != from_office.id])
            reason = random.choice([
                "Escalation to next level",
                "Re-routing to appropriate office",
                "Workload balancing",
                "Specialized handling required",
                "Jurisdiction change",
            ])
            transfer = Transfer.objects.create(
                case_id=case,
                from_office_id=from_office,
                to_office_id=to_office,
                reason=reason,
            )
            # reflect move on case
            case.office_id = to_office
            case.status_changed_by = case.added_by
            case.save(update_fields=["office_id", "status_changed_by"])
        self.stdout.write(self.style.SUCCESS("7 Transfers seeded."))

    def _seed_assignments(self, cases, staff_users):
        """
        Create 7 assignments between staff users.
        If staff list is empty, fall back to any users.
        """
        pool = staff_users or list(User.objects.all())
        if len(pool) < 2:
            self.stdout.write(self.style.WARNING("Not enough staff users to create assignments. Skipping."))
            return

        for _ in range(7):
            case = random.choice(cases)
            from_user, to_user = random.sample(pool, 2)
            reason = random.choice([
                "Workload balancing",
                "Subject matter expertise",
                "Schedule constraints",
                "Follow-up required",
                "Internal re-assignment",
            ])
            Assignment.objects.create(
                case_id=case,
                from_user_id=from_user,
                to_user_id=to_user,
                reason=reason,
            )
        self.stdout.write(self.style.SUCCESS("7 Assignments seeded."))
