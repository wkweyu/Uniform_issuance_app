from datetime import datetime
from decimal import Decimal
import io
import uuid

import pytest

import blueprints.exams.routes as exams_routes
import blueprints.fees.routes as fees_routes
import blueprints.finance.routes as finance_routes
import blueprints.farm.routes as farm_routes
import blueprints.inventory.routes as inventory_routes
import blueprints.procurement.routes as procurement_routes
import blueprints.students.routes as students_routes
import blueprints.students.services as students_services
import blueprints.transport.routes as transport_routes
import blueprints.classes.routes as classes_routes
from models import School


class DummyConnection:
    def close(self):
        return None


class FinanceServiceStub:
    last_instance = None
    create_voucher_error = None
    verify_voucher_error = None
    authorize_voucher_error = None

    def __init__(self, _connection):
        self.school_id = 7
        self.calls = []
        FinanceServiceStub.last_instance = self

    def create_voucher(self, payee, amount, mode, account_id, cheque_no, description, user_id, supplier_id=None, po_id=None, source_account_id=None, vat=Decimal("0"), wht=Decimal("0")):
        self.calls.append(("create_voucher", payee, amount, mode, account_id, cheque_no, description, user_id, supplier_id, po_id, source_account_id, vat, wht))
        if self.create_voucher_error is not None:
            raise self.create_voucher_error
        return 1

    def upsert_budget(self, account_id, annual_amount, fiscal_year, created_by):
        self.calls.append(("upsert_budget", account_id, annual_amount, fiscal_year, created_by))

    def get_budgets(self):
        self.calls.append(("get_budgets",))
        return [{"account_name": "Utilities", "account_code": "5000", "fiscal_year": 2026, "annual_amount": Decimal("120000.00")}]

    def get_accounts(self):
        self.calls.append(("get_accounts",))
        return [{"id": 1, "account_name": "Utilities", "account_code": "5000"}]

    def get_payment_mode_receiving_accounts(self):
        self.calls.append(("get_payment_mode_receiving_accounts",))
        return [{"payment_mode": "CASH", "account_id": 1, "account_code": "1000", "account_name": "Cash on Hand", "is_active": True}]

    def get_payment_mode_receiving_account_labels(self):
        self.calls.append(("get_payment_mode_receiving_account_labels",))
        return {"CASH": "1000 - Cash on Hand"}

    def configure_payment_mode_receiving_account(self, payment_mode, account_id, configured_by, is_active=True):
        self.calls.append(("configure_payment_mode_receiving_account", payment_mode, account_id, configured_by, is_active))

    def get_open_cashier_session(self, cashier_user_id):
        self.calls.append(("get_open_cashier_session", cashier_user_id))
        return None

    def get_cashier_sessions(self):
        self.calls.append(("get_cashier_sessions",))
        return []

    def open_cashier_session(self, cashier_user_id, opened_by):
        self.calls.append(("open_cashier_session", cashier_user_id, opened_by))
        return 1

    def close_cashier_session(self, session_id, cashier_user_id, actual_cash, closed_by, notes=''):
        self.calls.append(("close_cashier_session", session_id, cashier_user_id, actual_cash, closed_by, notes))
        return {"expected_cash": Decimal("0.00"), "actual_cash": actual_cash, "variance": actual_cash, "status": "CLOSED"}

    def approve_cashier_session_variance(self, session_id, approved_by):
        self.calls.append(("approve_cashier_session_variance", session_id, approved_by))

    def get_pending_purchase_orders(self):
        self.calls.append(("get_pending_purchase_orders",))
        return [{"id": 5, "po_number": "PO-001"}]

    def get_vouchers(self):
        self.calls.append(("get_vouchers",))
        return [{"id": 17, "voucher_no": "PV-2604-ABCD"}]

    def verify_voucher(self, voucher_id, user_id):
        self.calls.append(("verify_voucher", voucher_id, user_id))
        if self.verify_voucher_error is not None:
            raise self.verify_voucher_error

    def authorize_voucher(self, voucher_id, user_id, source_account_id):
        self.calls.append(("authorize_voucher", voucher_id, user_id, source_account_id))
        if self.authorize_voucher_error is not None:
            raise self.authorize_voucher_error


class FeesServiceStub:
    last_instance = None
    import_mpesa_error = None
    assign_waiver_error = None
    record_payment_error = None
    duplicate_payment = None
    allocation_templates = []

    def __init__(self, _connection):
        self.school_id = 7
        self.calls = []
        FeesServiceStub.last_instance = self

    def get_payment_mode_receiving_account_labels(self):
        self.calls.append(("get_payment_mode_receiving_account_labels",))
        return {"CASH": "1000 - Cash on Hand"}

    def get_receipt_details(self, payment_id):
        self.calls.append(("get_receipt_details", payment_id))
        return {"id": payment_id, "receipt_no": "RCP-2026-00077", "payment_mode": "CASH", "amount": Decimal("1500.00"), "FName": "Test", "SName": "Student"}

    def get_receipt_lifecycle(self, payment_id):
        self.calls.append(("get_receipt_lifecycle", payment_id))
        return [{"event_type": "CANCELLED", "status_after": "CANCELLED", "reason": "Wrong student", "actor_user_id": 10, "correlation_id": "correlation", "occurred_at": "2026-07-31"}]

    def record_receipt_print(self, payment_id, user_id):
        self.calls.append(("record_receipt_print", payment_id, user_id))
        return "PRINTED"

    def repost_cancelled_receipt(self, payment_id, new_reference, posting_date, user_id):
        self.calls.append(("repost_cancelled_receipt", payment_id, new_reference, posting_date, user_id))
        return {"payment_id": 88, "receipt_no": "RCP-2026-00088"}

    def archive_receipt(self, payment_id, reason, user_id):
        self.calls.append(("archive_receipt", payment_id, reason, user_id))

    def import_mpesa_statement(self, transactions):
        self.calls.append(("import_mpesa_statement", transactions))
        if self.import_mpesa_error is not None:
            raise self.import_mpesa_error
        return {"imported": len(transactions), "duplicates": 0}

    def assign_waiver_to_student(self, admno, category_id, year_id, term_id, user_id):
        self.calls.append(("assign_waiver_to_student", admno, category_id, year_id, term_id, user_id))
        if self.assign_waiver_error is not None:
            raise self.assign_waiver_error

    def record_payment(self, admno, amount, mode, reference, bank, date, year_id, term_id, user_id,
                       allocation_mode="AUTOMATIC", manual_allocations=None):
        self.calls.append(("record_payment", admno, amount, mode, reference, bank, date, year_id, term_id,
                           user_id, allocation_mode, manual_allocations))
        if self.record_payment_error is not None:
            raise self.record_payment_error
        return {
            "payment_id": 77,
            "receipt_no": "RCP-2026-00077",
            "balance": Decimal("250.00"),
            "allocations": [{"votehead_id": 4, "amount": 1000.0}],
        }

    def get_recent_terms(self):
        self.calls.append(("get_recent_terms",))
        return [{"id": 3, "term_number": 2}]

    def get_voteheads(self):
        self.calls.append(("get_voteheads",))
        return [{"id": 4, "name": "Tuition"}]

    def create_account_adjustment(self, admno, adjustment_type, votehead_id, amount, year_id, term_id, effective_date, reason, supporting_reference, user_id):
        self.calls.append(("create_account_adjustment", admno, adjustment_type, votehead_id, amount, year_id, term_id, effective_date, reason, supporting_reference, user_id))
        return 31

    def get_current_term_id(self):
        self.calls.append(("get_current_term_id",))
        return 3

    def get_student_balance(self, admno):
        self.calls.append(("get_student_balance", admno))
        return Decimal("850.00")

    def get_recent_payments(self, admno, limit=5):
        self.calls.append(("get_recent_payments", admno, limit))
        return [{"id": 77, "receipt_no": "RCP-2026-00077", "amount": Decimal("650.00")}]

    def get_outstanding_voteheads(self, admno):
        self.calls.append(("get_outstanding_voteheads", admno))
        return [{"votehead_id": 4, "votehead_name": "Tuition", "priority": 1, "outstanding": Decimal("850.00")}]

    def get_student_fee_structure(self, admno, term_id=None):
        self.calls.append(("get_student_fee_structure", admno, term_id))
        return [{"votehead_id": 4, "votehead_name": "Tuition", "amount": Decimal("1500.00"), "priority": 1}]

    def get_student_term_summary(self, admno, term_id):
        self.calls.append(("get_student_term_summary", admno, term_id))
        return {
            "charges": Decimal("1500.00"),
            "debits": Decimal("0.00"),
            "payments": Decimal("650.00"),
            "credits": Decimal("0.00"),
            "net_due": Decimal("850.00"),
        }

    def get_student_term_invoices(self, admno, term_id):
        self.calls.append(("get_student_term_invoices", admno, term_id))
        return [{"reference_no": "INV-1001-2026-3", "issued_on": "2026-01-15", "amount": Decimal("1500.00"), "item_count": 1}]

    def get_student_statement_summary(self, admno, year_id=None):
        self.calls.append(("get_student_statement_summary", admno, year_id))
        return [{"academic_year": 2026, "term_number": 1, "closing_balance": Decimal("850.00")}]

    def find_duplicate_payment(self, mode, reference):
        self.calls.append(("find_duplicate_payment", mode, reference))
        return self.duplicate_payment

    def get_allocation_templates(self):
        self.calls.append(("get_allocation_templates",))
        return self.allocation_templates

    def create_allocation_template(self, name, allocations, user_id):
        self.calls.append(("create_allocation_template", name, allocations, user_id))
        return {"id": 9, "name": name, "items": allocations}

    def get_student_statement(self, admno, year_id=None):
        self.calls.append(("get_student_statement", admno, year_id))
        return [{"admno": admno, "year_id": year_id, "balance": Decimal("0.00")}]

    def get_receipts_register(self, start_date, end_date, admno, mode, query_text=None, status=None):
        self.calls.append(("get_receipts_register", start_date, end_date, admno, mode, query_text, status))
        return [{"receipt_no": "RCP-1", "admno": admno, "mode": mode}]


class ProcurementServiceStub:
    last_instance = None
    create_requisition_error = None
    convert_requisition_error = None

    def __init__(self, _connection, school_id=None):
        self.school_id = school_id
        self.calls = []
        ProcurementServiceStub.last_instance = self

    def create_requisition(self, department_id, items, user_id, justification, category='General', academic_year_id=None):
        self.calls.append(("create_requisition", department_id, items, user_id, justification, category, academic_year_id))
        if self.create_requisition_error is not None:
            raise self.create_requisition_error

    def convert_requisition_to_po(self, req_id, supplier_id, user_id):
        self.calls.append(("convert_requisition_to_po", req_id, supplier_id, user_id))
        if self.convert_requisition_error is not None:
            raise self.convert_requisition_error
        return {"id": 88}

    def record_grn(self, po_id, user_id, items, delivery_note_ref, notes):
        self.calls.append(("record_grn", po_id, user_id, items, delivery_note_ref, notes))

    def register_asset(self, data, user_id):
        self.calls.append(("register_asset", data, user_id))

    def set_budget(self, department_id, year_id, category, allocated_amount):
        self.calls.append(("set_budget", department_id, year_id, category, allocated_amount))

    def record_po_payment(self, po_id, amount, payment_mode, reference_no, payment_date, user_id, source_account_id):
        self.calls.append(("record_po_payment", po_id, amount, payment_mode, reference_no, payment_date, user_id, source_account_id))

    def update_purchase_order(self, po_id, supplier_id, order_date, items, notes):
        self.calls.append(("update_purchase_order", po_id, supplier_id, order_date, items, notes))

    def get_suppliers(self, active_only=False):
        self.calls.append(("get_suppliers", active_only))
        return [{"supplierID": 4, "company": "Acme Supplies"}]

    def get_departments(self):
        self.calls.append(("get_departments",))
        return [{"departmentID": 2, "name": "Admin"}]

    def get_academic_years(self):
        self.calls.append(("get_academic_years",))
        return [{"id": 2026, "name": "2026"}]

    def get_current_academic_year_id(self):
        self.calls.append(("get_current_academic_year_id",))
        return 2026

    def get_budgets(self, year_id):
        self.calls.append(("get_budgets", year_id))
        return [{"department_name": "Admin", "allocated_amount": Decimal("50000.00")}]

    def get_stock_items(self):
        self.calls.append(("get_stock_items",))
        return [{"itemID": 1, "item_name": "Desk"}]

    def get_uniform_items_with_stock(self):
        self.calls.append(("get_uniform_items_with_stock",))
        return [{"item_name": "Blazer", "current_stock": 10}]

    def get_purchase_orders(self, status=None, po_number=None, supplier_id=None):
        self.calls.append(("get_purchase_orders", status, po_number, supplier_id))
        return [{"id": 12, "po_number": "PO-001", "supplier_id": supplier_id}]

    def get_purchase_order_status_counts(self):
        self.calls.append(("get_purchase_order_status_counts",))
        return {"pending": 1, "approved": 0}


class ExamServiceStub:
    last_instance = None
    save_mark_error = None

    def __init__(self, _connection):
        self.school_id = 7
        self.calls = []
        ExamServiceStub.last_instance = self

    def save_mark(self, exam_id, student_id, subject_id, mark, is_absent, remarks):
        self.calls.append((exam_id, student_id, subject_id, mark, is_absent, remarks))
        if self.save_mark_error is not None:
            raise self.save_mark_error
        return True

    def create_exam_series(self, name, academic_year_id, term, created_by, class_ids):
        self.calls.append(("create_exam_series", name, academic_year_id, term, created_by, class_ids))

    def assign_scale_to_class(self, class_id, scale_id):
        self.calls.append(("assign_scale_to_class", class_id, scale_id))


class StudentServiceStub:
    last_instance = None

    def __init__(self, _connection, school_id=None):
        self.school_id = school_id or 7
        self.calls = []
        StudentServiceStub.last_instance = self

    def get_student_by_admno(self, admno):
        self.calls.append(("get_student_by_admno", admno))
        return {"AdmNo": admno, "FName": "Ada", "MName": "", "SName": "Lovelace", "Sex": "F", "category": "Day", "student_group_name": "Scholarship"}

    def get_student_class_info(self, admno):
        self.calls.append(("get_student_class_info", admno))
        return {"class_name": "Grade 7 A", "class_group": "Grade 7-9", "stream": "A"}

    def clear_student_subject_enrollments(self, allocation_id):
        self.calls.append(("clear", allocation_id))


class ClassServiceStub:
    last_instance = None
    allocate_students_error = None
    replace_student_subjects_error = None
    allocate_subjects_error = None
    set_class_teacher_error = None
    allocate_teacher_error = None
    batch_enroll_error = None
    create_class_error = None
    promote_students_error = None
    stream_error = None

    def __init__(self, _connection, school_id=None):
        self.school_id = school_id
        self.calls = []
        ClassServiceStub.last_instance = self

    def enroll_student_in_subjects(self, allocation_id, subject_ids):
        self.calls.append(("enroll", allocation_id, subject_ids))

    def get_class_academic_year_id(self, class_id):
        self.calls.append(("get_class_academic_year_id", class_id))
        return 2026

    def allocate_subjects_to_class(self, class_id, subject_ids, compulsory=True):
        self.calls.append(("allocate_subjects_to_class", class_id, subject_ids, compulsory))
        if self.allocate_subjects_error is not None:
            raise self.allocate_subjects_error

    def set_class_teacher(self, class_id, teacher_id, ay_id):
        self.calls.append(("set_class_teacher", class_id, teacher_id, ay_id))
        if self.set_class_teacher_error is not None:
            raise self.set_class_teacher_error

    def allocate_teacher_to_class_subject(self, teacher_id, class_id, subject_id, ay_id):
        self.calls.append(("allocate_teacher_to_class_subject", teacher_id, class_id, subject_id, ay_id))
        if self.allocate_teacher_error is not None:
            raise self.allocate_teacher_error

    def enroll_all_students_in_class_subjects(self, class_id, subject_ids):
        self.calls.append(("enroll_all_students_in_class_subjects", class_id, subject_ids))
        if self.batch_enroll_error is not None:
            raise self.batch_enroll_error
        return len(subject_ids or [])

    def allocate_students_to_class(self, class_id, student_ids, academic_year_id=None):
        self.calls.append(("allocate_students_to_class", class_id, student_ids, academic_year_id))
        if self.allocate_students_error is not None:
            raise self.allocate_students_error
        return len(student_ids)

    def replace_student_subject_enrollments(self, allocation_id, subject_ids):
        self.calls.append(("replace_student_subject_enrollments", allocation_id, subject_ids))
        if self.replace_student_subjects_error is not None:
            raise self.replace_student_subjects_error

    def get_all_academic_years(self):
        self.calls.append(("get_all_academic_years",))
        if getattr(self, "get_all_academic_years_error", None) is not None:
            raise self.get_all_academic_years_error
        return [{"id": 2026, "is_current": True, "name": "2026"}]

    def get_active_classes(self):
        self.calls.append(("get_active_classes",))
        return [{"classID": 14, "display_name": "Grade 7 A"}]

    def get_class_groups(self):
        self.calls.append(("get_class_groups",))
        return {"Grade 7-9": {"name": "Grade 7-9"}}

    def get_allowed_streams(self, school_id=None):
        self.calls.append(("get_allowed_streams", school_id))
        return [{"code": "A", "name": "Stream A"}]

    def create_class(self, academic_year_id, class_group_code, stream_code, created_by, class_name):
        self.calls.append(("create_class", academic_year_id, class_group_code, stream_code, created_by, class_name))
        if self.create_class_error is not None:
            raise self.create_class_error

    def promote_students(self, old_class_id, new_class_id, promoted_by, notes=''):
        self.calls.append(("promote_students", old_class_id, new_class_id, promoted_by, notes))
        if self.promote_students_error is not None:
            raise self.promote_students_error
        return {"message": "Promotion completed"}

    def add_stream(self, stream_code, stream_name):
        self.calls.append(("add_stream", stream_code, stream_name))
        if self.stream_error is not None:
            raise self.stream_error

    def toggle_stream(self, stream_id):
        self.calls.append(("toggle_stream", stream_id))
        if self.stream_error is not None:
            raise self.stream_error

    def delete_stream(self, stream_id):
        self.calls.append(("delete_stream", stream_id))
        if self.stream_error is not None:
            raise self.stream_error

    def get_all_streams(self):
        self.calls.append(("get_all_streams",))
        return [{"id": 1, "code": "A", "name": "Stream A"}]

    def get_active_teachers(self):
        self.calls.append(("get_active_teachers",))
        return [{"userNo": 9, "username": "Teacher A"}]

    def get_active_subjects(self):
        self.calls.append(("get_active_subjects",))
        return [{"SubjectNo": 4, "SubjectName": "Math"}]

    def get_allocated_subject_ids(self, class_id):
        self.calls.append(("get_allocated_subject_ids", class_id))
        return [4]


class TransportServiceStub:
    last_instance = None
    add_bus_error = None
    delete_bus_error = None

    def __init__(self, _connection):
        self.calls = []
        TransportServiceStub.last_instance = self

    def add_bus(self, data):
        self.calls.append(("add_bus", data))
        if self.add_bus_error is not None:
            raise self.add_bus_error

    def get_buses(self):
        self.calls.append(("get_buses",))
        return [{"id": 1, "reg_no": "KAA 123A", "model": "ISUZU NQR", "make": "ISUZU NQR", "driver_name": "Jane", "capacity": 45, "current_mileage": 12000}]

    def get_bus_by_id(self, bus_id):
        self.calls.append(("get_bus_by_id", bus_id))
        return {"id": bus_id, "reg_no": "KAA 123A", "model": "ISUZU NQR", "make": "ISUZU NQR", "driver_name": "Jane", "capacity": 45, "current_mileage": 12000}

    def update_bus(self, bus_id, data):
        self.calls.append(("update_bus", bus_id, data))

    def get_fleet_dashboard_summary(self):
        self.calls.append(("get_fleet_dashboard_summary",))
        return {"bus_count": 1, "fuel_cost_total": Decimal("5400.00"), "service_cost_total": Decimal("3200.00")}

    def get_service_history(self):
        self.calls.append(("get_service_history",))
        return [{"id": 8, "service_date": "2026-04-01", "reg_no": "KAA 123A", "service_type": "Oil Change", "description": "Routine", "cost": Decimal("3200.00"), "garage_name": "Garage X", "mileage_at_service": 12000}]

    def get_fuel_vouchers(self, start_date=None, end_date=None):
        self.calls.append(("get_fuel_vouchers", start_date, end_date))
        return [{"id": 11, "voucher_no": "FV-2026-0001", "issued_on": datetime(2026, 4, 3, 8, 30), "reg_no": "KAA 123A", "driver_name": "Jane", "litres": Decimal("30.00"), "total_cost": Decimal("5400.00"), "invoiced": "No"}]

    def delete_bus(self, bus_id):
        self.calls.append(("delete_bus", bus_id))
        if self.delete_bus_error is not None:
            raise self.delete_bus_error


class FarmServiceStub:
    last_instance = None
    record_production_error = None

    def __init__(self, _connection):
        self.calls = []
        FarmServiceStub.last_instance = self

    def record_production(self, activity_id, quantity, spoilage, internal, recorded_by, notes=''):
        self.calls.append(("record_production", activity_id, quantity, spoilage, internal, recorded_by, notes))
        if self.record_production_error is not None:
            raise self.record_production_error


class InventoryServiceStub:
    last_instance = None
    process_issuance_error = None
    delete_item_error = None
    update_price_error = None
    adjust_stock_error = None

    def __init__(self, _connection):
        self.school_id = 7
        self.calls = []
        InventoryServiceStub.last_instance = self

    def add_uniform_item(self, item_name, class_groups):
        self.calls.append(("add_uniform_item", item_name, class_groups))

    def get_all_prices(self):
        self.calls.append(("get_all_prices",))
        return [{"item_name": "Blazer", "class_group": "Grade 1-3", "price": Decimal("1200.00")}]

    def get_class_groups(self):
        self.calls.append(("get_class_groups",))
        return [{"code": "Grade 1-3", "name": "Grade 1-3"}]

    def update_price(self, item_name, class_group, price):
        self.calls.append(("update_price", item_name, class_group, price))
        if self.update_price_error is not None:
            raise self.update_price_error

    def adjust_stock(self, item_name, quantity, movement_type, user_id, notes, purchase_ref=''):
        self.calls.append(("adjust_stock", item_name, quantity, movement_type, user_id, notes, purchase_ref))
        if self.adjust_stock_error is not None:
            raise self.adjust_stock_error

    def get_stock_levels(self):
        self.calls.append(("get_stock_levels",))
        return [{"item_name": "Blazer", "current_stock": 10}]

    def process_issuance(self, admno, items, user_id, receipt_no, total_amount):
        self.calls.append(("process_issuance", admno, items, user_id, receipt_no, total_amount))
        if self.process_issuance_error is not None:
            raise self.process_issuance_error
        return True

    def delete_uniform_item(self, item_name):
        self.calls.append(("delete_uniform_item", item_name))
        if self.delete_item_error is not None:
            raise self.delete_item_error


def _login_admin(client, school_id):
    with client.session_transaction() as session:
        session["userNo"] = 10
        session["school_id"] = school_id
        session["is_admin"] = True
        session["is_super_admin"] = True
        session["username"] = "admin"


def _create_school(db_session):
    suffix = uuid.uuid4().hex[:6].upper()
    school = School(name=f"Integration Tenant {suffix}", code=f"INT{suffix}")
    db_session.add(school)
    db_session.commit()
    return school


def test_finance_manage_budgets_route_uses_service_methods(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)
    monkeypatch.setattr(finance_routes, "render_template", lambda template, **context: f"{template}:{len(context['budgets'])}:{len(context['accounts'])}")

    response = client.post(
        "/admin/finance/budgets",
        data={"account_id": "1", "amount": "120000.00", "fiscal_year": "2026"},
    )

    assert response.status_code == 200
    assert b"manage_budgets.html:1:1" in response.data
    assert FinanceServiceStub.last_instance.calls == [
        ("upsert_budget", 1, Decimal("120000.00"), 2026, 10),
        ("get_budgets",),
        ("get_accounts",),
    ]


def test_finance_payment_mode_receiving_accounts_route_configures_mapping(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)
    monkeypatch.setattr(
        finance_routes,
        "render_template",
        lambda template, **context: f"{template}:{len(context['mappings'])}:{len(context['accounts'])}:{','.join(context['payment_modes'])}",
    )

    response = client.post(
        "/admin/finance/payment-mode-accounts",
        data={"payment_mode": "MPESA", "account_id": "1", "is_active": "on"},
    )

    assert response.status_code == 200
    assert b"manage_payment_mode_receiving_accounts.html:1:1:CASH,MPESA,BANK_TRANSFER,CHEQUE" in response.data
    assert FinanceServiceStub.last_instance.calls == [
        ("configure_payment_mode_receiving_account", "MPESA", 1, 10, True),
        ("get_payment_mode_receiving_accounts",),
        ("get_accounts",),
    ]


def test_finance_cashier_sessions_route_opens_current_cashier_session(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)

    response = client.post("/admin/finance/cashier-sessions", data={"action": "open"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/finance/cashier-sessions")
    assert FinanceServiceStub.last_instance.calls == [("open_cashier_session", 10, 10)]


def test_finance_authorize_voucher_route_passes_source_account_to_service(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)

    response = client.post(
        "/admin/finance/vouchers/17/authorize",
        data={"source_account_id": "21"},
    )

    assert response.status_code == 302
    assert FinanceServiceStub.last_instance.calls == [
        ("authorize_voucher", 17, 10, 21),
    ]


def test_finance_manage_vouchers_route_rejects_invalid_account_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)
    monkeypatch.setattr(finance_routes, "ProcurementService", ProcurementServiceStub)
    monkeypatch.setattr(finance_routes, "render_template", lambda template, **context: f"{template}:{len(context['vouchers'])}:{len(context['accounts'])}:{len(context['suppliers'])}:{len(context['pending_pos'])}")

    response = client.post(
        "/admin/finance/vouchers",
        data={"payee_name": "Vendor A", "amount": "1500.00", "account_id": "abc"},
    )

    assert response.status_code == 200
    assert b"manage_vouchers.html:1:1:1:1" in response.data
    assert all(call[0] != "create_voucher" for call in FinanceServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "account_id is required and must be a valid integer.")


def test_finance_manage_budgets_route_rejects_invalid_fiscal_year_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)
    monkeypatch.setattr(finance_routes, "render_template", lambda template, **context: f"{template}:{len(context['budgets'])}:{len(context['accounts'])}")

    response = client.post(
        "/admin/finance/budgets",
        data={"account_id": "1", "amount": "120000.00", "fiscal_year": "bad-year"},
    )

    assert response.status_code == 200
    assert b"manage_budgets.html:1:1" in response.data
    assert all(call[0] != "upsert_budget" for call in FinanceServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "fiscal_year is required and must be a valid integer.")


def test_finance_authorize_voucher_route_rejects_invalid_source_account_id(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(finance_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(finance_routes, "FinanceService", FinanceServiceStub)

    response = client.post(
        "/admin/finance/vouchers/17/authorize",
        data={"source_account_id": "not-a-number"},
    )

    assert response.status_code == 302
    assert FinanceServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "source_account_id must be a valid integer.")


def test_fees_import_mpesa_route_rejects_invalid_file_type(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)

    response = client.post(
        "/api/fees/import-mpesa",
        data={"file": (io.BytesIO(b"not,csv"), "statement.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Invalid file format. Upload CSV"}


def test_fees_import_mpesa_route_rejects_csv_parse_errors_with_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)

    response = client.post(
        "/api/fees/import-mpesa",
        data={"file": (io.BytesIO(b"Receipt No,Paid In\nABC,not-a-number\n"), "statement.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["success"] is False
    assert response.json["message"].startswith("Error parsing CSV:")


def test_fees_import_mpesa_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    FeesServiceStub.import_mpesa_error = fees_routes.FeesError("Transaction batch does not belong to the active school.")
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.post(
        "/api/fees/import-mpesa",
        data={"file": (io.BytesIO(b"Receipt No,Paid In,Details\nABC123,1500.00,Parent Payment\n"), "statement.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Transaction batch does not belong to the active school."}
    assert FeesServiceStub.last_instance.calls == [
        (
            "import_mpesa_statement",
            [{
                "transaction_no": "ABC123",
                "amount": Decimal("1500.00"),
                "sender_name": "Parent Payment",
                "sender_phone": "",
                "transaction_time": None,
            }],
        )
    ]

    FeesServiceStub.import_mpesa_error = None


def test_fees_assign_waiver_route_rejects_invalid_admno_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.post(
        "/fees/waiver/assign",
        data={"admno": "bad", "category_id": "2", "year_id": "2026", "term_id": "3"},
    )

    assert response.status_code == 302
    assert FeesServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "admno is required and must be a valid integer.")


def test_fees_collect_route_rejects_invalid_amount_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(fees_routes, "render_template", lambda template, **context: f"{template}:{len(context['years'])}:{len(context['terms'])}")

    response = client.post(
        "/admin/fees/collect",
        data={"admno": "1001", "amount": "bad", "mode": "CASH", "year_id": "2026", "term_id": "3"},
    )

    assert response.status_code == 200
    assert b"collect_fees.html:1:1" in response.data
    assert all(call[0] != "record_payment" for call in FeesServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "amount must be a valid number.")


def test_fees_collect_route_forwards_manual_allocations_for_ajax_post(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/admin/fees/collect",
        json={
            "admno": 1001,
            "amount": "1500.00",
            "mode": "MPESA",
            "reference": " QWE123 ",
            "bank": "",
            "date": "2026-04-03",
            "year_id": 2026,
            "term_id": 3,
            "allocation_mode": "MANUAL",
            "manual_allocations": [{"votehead_id": 4, "amount": "1000.00"}],
        },
    )

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "message": "Payment received. Receipt No: RCP-2026-00077",
        "receipt_no": "RCP-2026-00077",
        "payment_id": 77,
        "balance": 250.0,
        "allocations": [{"votehead_id": 4, "amount": 1000.0}],
    }
    assert FeesServiceStub.last_instance.calls == [
        (
            "record_payment", 1001, Decimal("1500.00"), "MPESA", "QWE123", "", "2026-04-03",
            2026, 3, 10, "MANUAL", [{"votehead_id": 4, "amount": "1000.00"}],
        )
    ]


def test_fees_collect_route_hides_workspace_initialization_traceback(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(ClassServiceStub, "get_all_academic_years_error", RuntimeError("database password exposed"), raising=False)

    response = client.get("/admin/fees/collect")

    assert response.status_code == 500
    assert response.data == b"Unable to load the bursar workspace. Please try again later."
    assert b"database password exposed" not in response.data
    assert b"Traceback" not in response.data


def test_fees_student_context_returns_ledger_outstanding_voteheads(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(students_services, "StudentService", StudentServiceStub)

    response = client.get("/api/fees/student-context?admno=1001")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["admno"] == 1001
    assert response.json["stream"] == "A"
    assert response.json["student_group"] == "Scholarship"
    assert response.json["outstanding_balance"] == 850.0
    assert response.json["structure_items"] == [
        {"votehead_id": 4, "votehead_name": "Tuition", "amount": 1500.0, "priority": 1}
    ]
    assert response.json["outstanding_voteheads"] == [
        {"votehead_id": 4, "votehead_name": "Tuition", "amount": 850.0, "priority": 1}
    ]
    assert response.json["financial_alerts"] == []
    assert response.json["term_summary"] == {
        "charges": 1500.0,
        "debits": 0.0,
        "payments": 650.0,
        "credits": 0.0,
        "net_due": 850.0,
    }
    assert response.json["term_invoices"] == [
        {"reference_no": "INV-1001-2026-3", "issued_on": "2026-01-15", "amount": 1500.0, "item_count": 1}
    ]
    assert ("get_outstanding_voteheads", 1001) in FeesServiceStub.last_instance.calls


def test_fees_duplicate_payment_preflight_returns_tenant_scoped_result(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    clear_response = client.get("/api/fees/payment-duplicate?mode=mpesa&reference=QWE123")

    assert clear_response.status_code == 200
    assert clear_response.json == {"duplicate": False}
    assert FeesServiceStub.last_instance.calls == [("find_duplicate_payment", "MPESA", "QWE123")]

    FeesServiceStub.duplicate_payment = {
        "id": 77,
        "admno": 1001,
        "amount": Decimal("1500.00"),
        "payment_date": "2026-07-30",
        "receipt_no": "RCP-2026-00077",
    }
    duplicate_response = client.get("/api/fees/payment-duplicate?mode=MPESA&reference=QWE123")

    assert duplicate_response.status_code == 200
    assert duplicate_response.json == {
        "duplicate": True,
        "payment": {
            "id": 77,
            "admno": 1001,
            "amount": 1500.0,
            "payment_date": "2026-07-30",
            "receipt_no": "RCP-2026-00077",
        },
    }
    FeesServiceStub.duplicate_payment = None


def test_fees_allocation_template_api_loads_and_saves_for_admin(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    FeesServiceStub.allocation_templates = [{"id": 4, "name": "Tuition First", "items": []}]

    get_response = client.get("/api/fees/allocation-templates")
    post_response = client.post(
        "/api/fees/allocation-templates",
        json={"name": "Boarding Split", "allocations": [{"votehead_id": 4, "amount": 1000}]},
    )

    assert get_response.status_code == 200
    assert get_response.json == {"templates": [{"id": 4, "name": "Tuition First", "items": []}]}
    assert post_response.status_code == 201
    assert post_response.json == {
        "success": True,
        "template": {"id": 9, "name": "Boarding Split", "items": [{"votehead_id": 4, "amount": 1000}]},
    }
    assert FeesServiceStub.last_instance.calls == [
        ("create_allocation_template", "Boarding Split", [{"votehead_id": 4, "amount": 1000}], 10),
    ]
    FeesServiceStub.allocation_templates = []


def test_fees_allocation_template_api_blocks_non_admin_save(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    with client.session_transaction() as session:
        session["is_admin"] = False

    response = client.post(
        "/api/fees/allocation-templates",
        json={"name": "Boarding Split", "allocations": [{"votehead_id": 4, "amount": 1000}]},
    )

    assert response.status_code == 403
    assert response.json == {"success": False, "message": "Administrator access is required."}


def test_fees_student_context_returns_blocked_credit_alerts(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(students_services, "StudentService", StudentServiceStub)
    monkeypatch.setattr(
        StudentServiceStub,
        "get_student_by_admno",
        lambda self, admno: {"AdmNo": admno, "FName": "Ada", "SName": "Lovelace", "blocked": "YES"},
    )
    monkeypatch.setattr(FeesServiceStub, "get_student_balance", lambda self, admno: Decimal("-250.00"))

    response = client.get("/api/fees/student-context?admno=1001")

    assert response.status_code == 200
    assert response.json["financial_alerts"] == [
        {
            "code": "BLOCKED_ACCOUNT",
            "severity": "warning",
            "message": "This student account is blocked. Confirm the account status before posting.",
        },
        {
            "code": "CREDIT_BALANCE",
            "severity": "info",
            "message": "This student has a credit balance of KES 250.00.",
        },
    ]


def test_fees_bulk_post_route_reports_malformed_rows_explicitly(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.post(
        "/admin/fees/bulk_post",
        data={
            "file": (
                io.BytesIO(
                    b"admno,amount,mode,reference,bank,date,year_id,term_id\n"
                    b"1001,1500.00,CASH,REF-1,Equity,2026-04-03,2026,2\n"
                    b"1002,bad,CASH,REF-2,Equity,2026-04-03,2026,2\n"
                ),
                "bulk-post.csv",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert FeesServiceStub.last_instance.calls == [
        (
            "record_payment", 1001, Decimal("1500.00"), "CASH", "REF-1", "Equity", "2026-04-03",
            2026, 2, 10, "AUTOMATIC", None,
        ),
    ]
    with client.session_transaction() as session:
        flashes = session.get("_flashes")
        assert ("success", "Bulk posting complete. Posted: 1") in flashes
        assert any(
            category == "error" and "Bulk posting encountered 1 row error(s). Row 3: amount must be a valid number." in message
            for category, message in flashes
        )


def test_transport_manage_buses_route_rejects_invalid_capacity_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(transport_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(transport_routes, "TransportService", TransportServiceStub)
    monkeypatch.setattr(transport_routes, "render_template", lambda template, **context: f"{template}:{len(context['buses'])}")

    response = client.post(
        "/fleet/buses",
        data={"reg_no": "KAA 123A", "model": "Isuzu", "capacity": "bad", "current_mileage": "12000", "driver_name": "Jane"},
    )

    assert response.status_code == 200
    assert b"manage_buses.html:1" in response.data
    assert TransportServiceStub.last_instance.calls == [("get_buses",)]
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "capacity is required and must be a valid integer.")


def test_transport_delete_bus_route_maps_service_validation_to_flash(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    TransportServiceStub.delete_bus_error = ValueError("Bus not found for the active school.")
    monkeypatch.setattr(transport_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(transport_routes, "TransportService", TransportServiceStub)

    response = client.post("/fleet/delete_bus/99")

    assert response.status_code == 302
    assert TransportServiceStub.last_instance.calls == [("delete_bus", 99)]
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "Bus not found for the active school.")

    TransportServiceStub.delete_bus_error = None


@pytest.mark.parametrize(
    ("path", "expected_text"),
    [
        ("/fleet/fleet_dashboard", b"Fleet Management Dashboard"),
        ("/fleet/buses", b"Manage School Buses"),
        ("/fleet/record_service", b"Record Bus Service"),
        ("/fleet/service_register", b"Service Register"),
        ("/fleet/issue_fuel", b"Issue Fuel Voucher"),
        ("/fuel/voucher_register", b"Fuel Voucher & Invoice Register"),
        ("/fleet/service_reminders", b"Upcoming Service Reminders"),
    ],
)
def test_transport_core_pages_render_without_template_errors(client, db_session, monkeypatch, path, expected_text):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(transport_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(transport_routes, "TransportService", TransportServiceStub)

    response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.data


def test_procurement_create_requisition_route_rejects_invalid_department_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)
    monkeypatch.setattr(procurement_routes, "render_template", lambda template, **context: f"{template}:{len(context['depts'])}:{len(context['academic_years'])}")

    response = client.post(
        "/admin/procurement/requisition/create",
        data={"department_id": "bad", "description[]": ["Printer"], "quantity[]": ["2"], "price[]": ["45000"], "justification": "Office"},
    )

    assert response.status_code == 200
    assert b"create_requisition.html:1:1" in response.data
    assert all(call[0] != "create_requisition" for call in ProcurementServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "department_id is required and must be a valid integer.")


def test_procurement_convert_requisition_route_rejects_invalid_supplier_id(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)

    response = client.post(
        "/admin/procurement/requisition/12/convert",
        data={"supplier_id": "bad"},
    )

    assert response.status_code == 302
    assert ProcurementServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "supplier_id is required and must be a valid integer.")


def test_procurement_manage_budgets_route_rejects_invalid_amount_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)
    monkeypatch.setattr(procurement_routes, "render_template", lambda template, **context: f"{template}:{len(context['budgets'])}:{len(context['departments'])}:{len(context['academic_years'])}:{context['current_year_id']}")

    response = client.post(
        "/admin/procurement/budgets",
        data={"department_id": "2", "category": "General", "allocated_amount": "bad"},
    )

    assert response.status_code == 200
    assert b"procurement_budgets.html:1:1:1:2026" in response.data
    assert all(call[0] != "set_budget" for call in ProcurementServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "allocated_amount must be a valid number.")


def test_procurement_po_payment_route_rejects_invalid_source_account_id(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)

    response = client.post(
        "/admin/procurement/po/44/pay",
        data={"amount": "2500.00", "payment_mode": "BANK", "reference_no": "BANK-1", "payment_date": "2026-04-01", "source_account_id": "bad"},
    )

    assert response.status_code == 302
    assert ProcurementServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "source_account_id is required and must be a valid integer.")


def test_class_create_route_rejects_invalid_academic_year_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(classes_routes, "render_template", lambda template, **context: f"{template}:{len(context['years'])}:{len(context['groups'])}:{len(context['streams'])}")

    response = client.post(
        "/admin/classes/create",
        data={"academic_year_id": "bad", "class_group_code": "Grade 7-9", "stream_code": "A", "class_name": "Grade 7"},
    )

    assert response.status_code == 200
    assert b"create_class.html:1:1:1" in response.data
    assert all(call[0] != "create_class" for call in ClassServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "Error creating class: academic_year_id is required and must be a valid integer.")


def test_class_manage_streams_route_rejects_invalid_stream_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(classes_routes, "render_template", lambda template, **context: f"{template}:{len(context['streams'])}")

    response = client.post(
        "/admin/manage_streams",
        data={"action": "toggle", "stream_id": "bad"},
    )

    assert response.status_code == 200
    assert b"manage_streams.html:1" in response.data
    assert all(call[0] != "toggle_stream" for call in ClassServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "stream_id is required and must be a valid integer.")


def test_exams_create_route_rejects_invalid_academic_year_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(exams_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(exams_routes, "ExamManagementService", ExamServiceStub)
    monkeypatch.setattr(exams_routes, "ClassManagementService", ClassServiceStub)
    monkeypatch.setattr(exams_routes, "render_template", lambda template, **context: f"{template}:{len(context['years'])}:{len(context['classes'])}")

    response = client.post(
        "/admin/exams/create",
        data={"name": "Midterm", "academic_year_id": "bad", "term": "2", "class_ids": ["14"]},
    )

    assert response.status_code == 200
    assert b"create_exam.html:1:1" in response.data
    assert all(call[0] != "create_exam_series" for call in ExamServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "academic_year_id is required and must be a valid integer.")


def test_inventory_manage_uniform_items_route_rejects_invalid_price_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)
    monkeypatch.setattr(inventory_routes, "render_template", lambda template, **context: f"{template}:{len(context['prices'])}:{len(context['class_groups'])}")

    response = client.post(
        "/manage_uniform_items",
        data={"item_name": "Blazer", "class_group": "Grade 1-3", "price": "bad"},
    )

    assert response.status_code == 302
    assert all(call[0] != "update_price" for call in InventoryServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "Error: price must be a valid number.")


def test_inventory_manage_stock_route_rejects_invalid_quantity_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)
    monkeypatch.setattr(inventory_routes, "render_template", lambda template, **context: f"{template}:{len(context['items'])}")

    response = client.post(
        "/manage_stock",
        data={"action": "add_stock", "item_name": "Blazer", "quantity": "bad", "supplier": "Acme", "purchase_ref": "PO-1"},
    )

    assert response.status_code == 200
    assert b"manage_stock.html:1" in response.data
    assert all(call[0] != "adjust_stock" for call in InventoryServiceStub.last_instance.calls)
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "quantity is required and must be a valid integer.")


def test_students_enroll_subjects_route_rejects_invalid_class_allocation_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "StudentService", StudentServiceStub)
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/admin/student/1001/subjects",
        data={"class_allocation_id": "bad", "subject_ids": ["4", "5"]},
    )

    assert response.status_code == 302
    assert ClassServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "Error enrolling student: class_allocation_id must be a valid integer.")


def test_farm_record_production_route_rejects_invalid_quantity_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(farm_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(farm_routes, "FarmManagementService", FarmServiceStub)

    response = client.post(
        "/farm/production",
        data={"activity_id": "3", "quantity": "bad", "spoilage": "0", "internal": "0", "notes": "Morning yield"},
    )

    assert response.status_code == 302
    assert FarmServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "Error: quantity must be a valid number.")


def test_exams_save_mark_route_passes_payload_to_service(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(exams_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(exams_routes, "ExamManagementService", ExamServiceStub)

    response = client.post(
        "/api/exams/5/save-mark",
        json={"student_id": "1001", "subject_id": 12, "mark": 71, "is_absent": False, "remarks": "steady"},
    )

    assert response.status_code == 200
    assert response.json == {"success": True}
    assert ExamServiceStub.last_instance.calls == [(5, "1001", 12, 71, False, "steady")]


def test_exams_save_mark_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(exams_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(exams_routes, "ExamManagementService", ExamServiceStub)

    response = client.post(
        "/api/exams/5/save-mark",
        json={"subject_id": 12, "mark": 71},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "student_id is required."}


def test_exams_save_mark_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ExamServiceStub.save_mark_error = ValueError("Student, subject, and exam assignment do not match for the active school.")
    monkeypatch.setattr(exams_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(exams_routes, "ExamManagementService", ExamServiceStub)

    response = client.post(
        "/api/exams/5/save-mark",
        json={"student_id": "1001", "subject_id": 12, "mark": 71},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Student, subject, and exam assignment do not match for the active school."}
    assert ExamServiceStub.last_instance.calls == [(5, "1001", 12, 71, False, "")]

    ExamServiceStub.save_mark_error = None


def test_exams_save_mark_route_rejects_invalid_subject_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(exams_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(exams_routes, "ExamManagementService", ExamServiceStub)

    response = client.post(
        "/api/exams/5/save-mark",
        json={"student_id": "1001", "subject_id": "bad", "mark": 71},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "subject_id is required and must be a valid integer."}
    assert ExamServiceStub.last_instance.calls == []


def test_student_subject_update_route_uses_service_layer(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/student/subjects/update",
        json={"allocation_id": 22, "subject_ids": [3, 5, 8]},
    )

    assert response.status_code == 200
    assert response.json == {"success": True, "message": "Student subjects updated successfully"}
    assert ClassServiceStub.last_instance.calls == [("replace_student_subject_enrollments", 22, [3, 5, 8])]


def test_student_subject_update_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/student/subjects/update",
        json={"subject_ids": [3, 5, 8]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "allocation_id is required."}


def test_student_subject_update_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.replace_student_subjects_error = ValueError("Class allocation not found for the active school.")
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/student/subjects/update",
        json={"allocation_id": 999, "subject_ids": [3, 5, 8]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Class allocation not found for the active school."}
    assert ClassServiceStub.last_instance.calls == [("replace_student_subject_enrollments", 999, [3, 5, 8])]


def test_student_subject_update_route_rejects_invalid_allocation_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/student/subjects/update",
        json={"allocation_id": "bad", "subject_ids": [3, 5, 8]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "allocation_id must be a valid integer."}
    assert ClassServiceStub.last_instance.calls == []

    ClassServiceStub.replace_student_subjects_error = None


def test_remove_student_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.allocate_students_error = None
    ClassServiceStub.replace_student_subjects_error = None
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)
    ClassServiceStub.last_instance = None
    ClassServiceStub.allocate_students_error = None
    ClassServiceStub.replace_student_subjects_error = None

    original_remove = getattr(ClassServiceStub, 'remove_student_from_class', None)

    def _raise_remove(self, allocation_id):
        self.calls.append(("remove_student_from_class", allocation_id))
        raise ValueError("Class allocation not found for the active school.")

    ClassServiceStub.remove_student_from_class = _raise_remove
    try:
        response = client.post("/api/class/remove-student/999")
    finally:
        if original_remove is None:
            delattr(ClassServiceStub, 'remove_student_from_class')
        else:
            ClassServiceStub.remove_student_from_class = original_remove

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Class allocation not found for the active school."}
    assert ClassServiceStub.last_instance.calls == [("remove_student_from_class", 999)]


def test_class_add_students_route_uses_service_layer(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/add-students",
        json={"student_ids": ["1001", "1002"]},
    )

    assert response.status_code == 200
    assert response.json == {"success": True, "message": "Successfully added 2 students"}
    assert ClassServiceStub.last_instance.calls == [
        ("allocate_students_to_class", 14, [1001, 1002], None),
    ]


def test_class_add_students_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/add-students",
        json={"student_ids": "1001"},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "student_ids must be a non-empty list."}


def test_class_add_students_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.allocate_students_error = ValueError("One or more students do not belong to the active school.")
    monkeypatch.setattr(students_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(students_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/add-students",
        json={"student_ids": ["1001", "9999"]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "One or more students do not belong to the active school."}
    assert ClassServiceStub.last_instance.calls == [
        ("allocate_students_to_class", 14, [1001, 9999], None),
    ]

    ClassServiceStub.allocate_students_error = None


def test_class_assign_teacher_route_uses_service_layer(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/assign-teacher",
        json={"teacher_id": 9, "subject_id": 4, "is_class_teacher": True},
    )

    assert response.status_code == 200
    assert response.json == {"success": True, "message": "Teacher assigned successfully"}
    assert ClassServiceStub.last_instance.calls == [
        ("get_class_academic_year_id", 14),
        ("set_class_teacher", 14, 9, 2026),
        ("allocate_teacher_to_class_subject", 9, 14, 4, 2026),
    ]


def test_class_update_subjects_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/update-subjects",
        json={"subject_ids": "4"},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "subject_ids must be a list."}


def test_class_update_subjects_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.allocate_subjects_error = ValueError("One or more subjects do not belong to the active school.")
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/update-subjects",
        json={"subject_ids": [4, 5]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "One or more subjects do not belong to the active school."}
    assert ClassServiceStub.last_instance.calls == [("allocate_subjects_to_class", 14, [4, 5], True)]

    ClassServiceStub.allocate_subjects_error = None


def test_class_update_subjects_route_rejects_invalid_subject_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/update-subjects",
        json={"subject_ids": ["bad"]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "subject_id is required and must be a valid integer."}
    assert ClassServiceStub.last_instance.calls == []


def test_class_assign_teacher_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/assign-teacher",
        json={"subject_id": 4},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "teacher_id is required."}


def test_class_assign_teacher_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.set_class_teacher_error = ValueError("Teacher not found for the active school.")
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/assign-teacher",
        json={"teacher_id": 9, "is_class_teacher": True},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Teacher not found for the active school."}
    assert ClassServiceStub.last_instance.calls == [
        ("get_class_academic_year_id", 14),
        ("set_class_teacher", 14, 9, 2026),
    ]

    ClassServiceStub.set_class_teacher_error = None


def test_class_assign_teacher_route_rejects_invalid_teacher_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/assign-teacher",
        json={"teacher_id": "bad", "subject_id": 4},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "teacher_id is required and must be a valid integer."}
    assert ClassServiceStub.last_instance.calls == []


def test_class_batch_enroll_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/batch-enroll-subjects",
        json={"subject_ids": "4"},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "subject_ids must be a list when provided."}


def test_class_batch_enroll_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    ClassServiceStub.batch_enroll_error = ValueError("One or more subjects are not allocated to the student's class.")
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/batch-enroll-subjects",
        json={"subject_ids": [4]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "One or more subjects are not allocated to the student's class."}
    assert ClassServiceStub.last_instance.calls == [("enroll_all_students_in_class_subjects", 14, [4])]

    ClassServiceStub.batch_enroll_error = None


def test_class_batch_enroll_route_rejects_invalid_subject_id_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(classes_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, "ClassManagementService", ClassServiceStub)

    response = client.post(
        "/api/class/14/batch-enroll-subjects",
        json={"subject_ids": ["bad"]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "subject_id is required and must be a valid integer."}
    assert ClassServiceStub.last_instance.calls == []


def test_inventory_manage_uniform_items_route_uses_service_reference_methods(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)
    monkeypatch.setattr(inventory_routes, "render_template", lambda template, **context: f"{template}:{len(context['prices'])}:{len(context['class_groups'])}")

    response = client.get("/manage_uniform_items")

    assert response.status_code == 200
    assert b"manage_prices.html:1:1" in response.data
    assert InventoryServiceStub.last_instance.calls == [
        ("get_all_prices",),
        ("get_class_groups",),
    ]


def test_inventory_submit_issuance_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)

    response = client.post(
        "/submit_issuance",
        json={"admno": "", "items": []},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Student admission number is required."}


def test_inventory_submit_issuance_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    InventoryServiceStub.process_issuance_error = ValueError("Student not found for the active school.")
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)

    response = client.post(
        "/submit_issuance",
        json={"admno": "9999", "items": [{"item_name": "Blazer", "quantity": 1, "price": 1200, "total": 1200}]},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Student not found for the active school."}
    assert InventoryServiceStub.last_instance.calls[0][0] == "process_issuance"

    InventoryServiceStub.process_issuance_error = None


def test_inventory_delete_uniform_item_route_rejects_malformed_payload(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)

    response = client.post(
        "/admin/delete_uniform_item",
        json={},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "item_name is required."}


def test_inventory_delete_uniform_item_route_maps_service_validation_to_400(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    InventoryServiceStub.delete_item_error = ValueError("Item not found for the active school.")
    monkeypatch.setattr(inventory_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(inventory_routes, "InventoryService", InventoryServiceStub)

    response = client.post(
        "/admin/delete_uniform_item",
        json={"item_name": "Blazer"},
    )

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "Item not found for the active school."}
    assert InventoryServiceStub.last_instance.calls == [("delete_uniform_item", "Blazer")]

    InventoryServiceStub.delete_item_error = None


def test_procurement_po_payment_route_passes_source_account_to_service(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)

    response = client.post(
        "/admin/procurement/po/44/pay",
        data={
            "amount": "2500.00",
            "payment_mode": "BANK",
            "reference_no": "BANK-1",
            "payment_date": "2026-04-01",
            "source_account_id": "9",
        },
    )

    assert response.status_code == 302
    assert ProcurementServiceStub.last_instance.calls == [
        ("record_po_payment", 44, Decimal("2500.00"), "BANK", "BANK-1", "2026-04-01", 10, 9),
    ]


def test_procurement_edit_purchase_order_route_uses_service_layer(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)

    response = client.post(
        "/admin/procurement/po/12/edit",
        data={
            "supplier_id": "4",
            "order_date": "2026-04-02",
            "notes": "Updated quantities",
            "item_id[]": ["1", ""],
            "item_description[]": ["Desk", "Chalk"],
            "item_qty[]": ["3", "5"],
            "item_price[]": ["1200", "150"],
        },
    )

    assert response.status_code == 302
    assert ProcurementServiceStub.last_instance.calls == [
        (
            "update_purchase_order",
            12,
            4,
            "2026-04-02",
            [
                {"item_id": 1, "description": "Desk", "quantity": 3.0, "unit_price": 1200.0},
                {"item_id": None, "description": "Chalk", "quantity": 5.0, "unit_price": 150.0},
            ],
            "Updated quantities",
        ),
    ]


def test_fees_statement_route_rejects_invalid_admno_before_service_call(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.get("/api/fees/statement?admno=bad")

    assert response.status_code == 400
    assert response.json == {"success": False, "message": "admno is required and must be a valid integer."}
    assert FeesServiceStub.last_instance.calls == []


def test_fees_statement_summary_route_returns_tenant_service_summary(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.get("/api/fees/statement-summary?admno=1001&year_id=4")

    assert response.status_code == 200
    assert response.json[0]["academic_year"] == 2026
    assert FeesServiceStub.last_instance.calls == [("get_student_statement_summary", 1001, 4)]


def test_fee_receipts_register_route_rejects_invalid_admno_filter(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "render_template", lambda template, **context: f"{template}:{len(context['records'])}")

    response = client.get("/admin/fees/receipts?admno=bad")

    assert response.status_code == 200
    assert b"fee_receipts_register.html:0" in response.data
    assert FeesServiceStub.last_instance.calls == []
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "admno must be a valid integer.")


def test_receipt_lifecycle_route_loads_receipt_and_events(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "render_template", lambda template, **context: f"{template}:{context['receipt']['receipt_no']}:{len(context['events'])}")

    response = client.get("/admin/fees/receipt/77/lifecycle")

    assert response.status_code == 200
    assert b"fee_receipt_lifecycle.html:RCP-2026-00077:1" in response.data
    assert FeesServiceStub.last_instance.calls == [("get_receipt_details", 77), ("get_receipt_lifecycle", 77)]


def test_repost_fee_receipt_route_posts_new_reference(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.post("/admin/fees/receipt/77/repost", data={"reference": "MPESA-NEW", "posting_date": "2026-07-31"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/fees/receipt/88")
    assert FeesServiceStub.last_instance.calls == [("repost_cancelled_receipt", 77, "MPESA-NEW", "2026-07-31", 10)]


def test_print_fee_receipt_route_records_lifecycle_event(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "render_template", lambda template, **context: f"{template}:{context['receipt']['receipt_no']}")

    response = client.get("/admin/fees/receipt/77")

    assert response.status_code == 200
    assert b"print_fee_receipt.html:RCP-2026-00077" in response.data
    assert FeesServiceStub.last_instance.calls == [("get_receipt_details", 77), ("record_receipt_print", 77, 10)]


def test_archive_fee_receipt_route_records_reason(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)

    response = client.post("/admin/fees/receipt/77/archive", data={"reason": "End of year retention"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/fees/receipt/77/lifecycle")
    assert FeesServiceStub.last_instance.calls == [("archive_receipt", 77, "End of year retention", 10)]


def test_fee_adjustment_route_posts_typed_adjustment(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(fees_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(fees_routes, "FeesService", FeesServiceStub)
    monkeypatch.setattr(fees_routes, "ClassManagementService", ClassServiceStub)

    response = client.post("/admin/fees/adjustments", data={
        "admno": "1001", "adjustment_type": "CREDIT", "votehead_id": "4", "amount": "250.00",
        "year_id": "2026", "term_id": "3", "effective_date": "2026-07-31",
        "reason": "Approved correction", "supporting_reference": "CASE-42",
    })

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/fees/adjustments")
    assert FeesServiceStub.last_instance.calls == [
        ("create_account_adjustment", 1001, "CREDIT", 4, Decimal("250.00"), 2026, 3, "2026-07-31", "Approved correction", "CASE-42", 10),
    ]


def test_procurement_dashboard_route_rejects_invalid_supplier_filter(client, db_session, monkeypatch):
    school = _create_school(db_session)
    _login_admin(client, school.id)
    monkeypatch.setattr(procurement_routes, "get_db_connection", lambda: DummyConnection())
    monkeypatch.setattr(procurement_routes, "ProcurementService", ProcurementServiceStub)
    monkeypatch.setattr(procurement_routes, "render_template", lambda template, **context: f"{template}:{len(context['pos'])}:{len(context['suppliers'])}")

    response = client.get("/admin/procurement?supplier_id=bad")

    assert response.status_code == 200
    assert b"procurement_dashboard.html:0:1" in response.data
    assert ProcurementServiceStub.last_instance.calls == [
        ("get_suppliers", False),
        ("get_purchase_order_status_counts",),
    ]
    with client.session_transaction() as session:
        assert session.get("_flashes")[-1] == ("error", "supplier_id must be a valid integer.")
