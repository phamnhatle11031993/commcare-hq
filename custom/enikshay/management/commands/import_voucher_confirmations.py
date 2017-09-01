import csv
import datetime
import decimal
import math
from mock import MagicMock
from collections import defaultdict, Counter
from dateutil import parser as date_parser

from django.core.management.base import BaseCommand

from dimagi.utils.chunked import chunked
from dimagi.utils.decorators.memoized import memoized

from corehq.apps.hqcase.utils import bulk_update_cases
from corehq.form_processor.interfaces.dbaccessors import CaseAccessors
from corehq.motech.repeaters.models import RepeatRecord, RepeatRecordAttempt
from corehq.motech.repeaters.dbaccessors import iter_repeat_records_by_domain, get_repeat_record_count
from corehq.util.couch import IterDB
from corehq.util.log import with_progress_bar

from custom.enikshay.case_utils import CASE_TYPE_VOUCHER, get_person_case_from_voucher
from custom.enikshay.const import (
    VOUCHER_ID,
    AMOUNT_APPROVED,
    DATE_FULFILLED,
    DATE_APPROVED,
    FULFILLED_BY_ID,
    FULFILLED_BY_LOCATION_ID,
    INVESTIGATION_TYPE,
    VOUCHER_TYPE,
)
from custom.enikshay.integrations.bets.repeater_generators import VoucherPayload
from custom.enikshay.integrations.bets.views import VoucherUpdate


class Command(BaseCommand):
    help = """
    import payment confirmations of vouchers paid offline
    """
    voucher_dump_properties = [
        "Voucher ID (visible)",
        "Voucher ID (GUUID)",
        "Event Occur Date (Voucher Validation date)",
        "Event ID",
        "Beneficiary ID (visible)",
        "BenficiaryUUID",
        "BeneficiaryType",
        "Location (GUID)",
        "Amount",
        "DTOLocation",
        "DTOLocation (GUID)",
        "InvestigationType",
        "PersonId",
        "PersonId (GUID)",
        "AgencyId",
        "AgencyId (GUID)",
        "EnikshayApprover",
        "EnikshayRole",
        "EnikshayApprovalDate",
        "Succeeded",
    ]

    voucher_update_properties = [
        'id',
        'eventType',
        'EventID',
        'status',
        'failureDescription',
        'amount',
        'Beneficiary ID',
        'bankName',
        'paymentMode',
        'checkNumber',
        'comments',
        'paymentDate',
    ]

    voucher_api_properties = [
        'VoucherID',
        'EventOccurDate',
        'EventID',
        'BeneficiaryUUID',
        'BeneficiaryType',
        'Location',
        'Amount',
        'DTOLocation',
        'InvestigationType',
        'PersonId',
        'AgencyId',
        'EnikshayApprover',
        'EnikshayRole',
        'EnikshayApprovalDate',
    ]

    def add_arguments(self, parser):
        parser.add_argument('domain')
        parser.add_argument('filename')
        parser.add_argument(
            '--commit',
            action='store_true',
            dest='commit',
            default=False,
        )

    def handle(self, domain, filename, **options):
        self.domain = domain
        self.accessor = CaseAccessors(domain)
        self.commit = options['commit']
        self.bad_payloads = 0
        unidentifiable_vouchers = 0

        voucher_dicts = []  # The row-by-row upload confirmation
        voucher_updates = []

        for voucher_dict in self.get_voucher_dicts_from_dump_and_update():
            voucher_id = voucher_dict['id']
            possible_vouchers = self.vouchers_by_readable_id[voucher_id]
            voucher_dict['number possible vouchers'] = len(possible_vouchers)
            if len(possible_vouchers) == 0:
                voucher = None
                unidentifiable_vouchers += 1
                voucher_dict['voucher case_id'] = "NO MATCHES"
                voucher_dict['voucher found'] = "no"
            elif len(possible_vouchers) == 1:
                voucher = possible_vouchers[0]
                voucher_dict['voucher case_id'] = voucher.case_id
                voucher_dict['voucher found'] = "yes"
            else:
                voucher = self.get_voucher_from_list(possible_vouchers, voucher_dict)
                if voucher:
                    voucher_dict['voucher case_id'] = voucher.case_id
                    voucher_dict['voucher found'] = "yes"
                else:
                    unidentifiable_vouchers += 1
                    voucher_dict['voucher case_id'] = ' '.join(v.case_id for v in possible_vouchers)
                    voucher_dict['voucher found'] = "no"

            if not voucher:
                voucher_dict['confirmation status'] = "UNIDENTIFIABLE"
            elif self._missing_key_properties(voucher):
                voucher_dict['confirmation status'] = "UNIDENTIFIABLE"
            elif not self._is_approved(voucher):
                voucher_dict['confirmation status'] = voucher.get_case_property('state')
            else:
                voucher_dict['confirmation status'] = "ALL CHECKS SUCCESSFUL"
                voucher_updates.append(self.make_voucher_update(voucher, voucher_dict))

            voucher_dicts.append(voucher_dict)

        print 'Found {} unidentifiable_vouchers'.format(unidentifiable_vouchers)

        # TODO
        # print "{} unrecognized\n{} unapproved or incomplete\n{} to update".format()

        self.log_dump_confirmations(voucher_dicts)
        self.log_voucher_updates(voucher_updates)
        # self.log_all_vouchers_in_domain(case_id_to_confirmation_status)
        self.update_vouchers(voucher_updates)
        self.reconcile_repeat_records(voucher_updates)
        print "Couldn't generate payloads for {} vouchers".format(self.bad_payloads)

    def get_voucher_dicts_from_dump_and_update(self):
        """open the two files, join the rows together and return a list of dicts"""
        with open('voucher-export.csv') as dump_file:
            with open('voucher-confirmations.csv') as update_file:

                dump = csv.reader(dump_file)
                dump_headers = next(dump)
                if dump_headers != self.voucher_dump_properties:
                    raise AssertionError("Dump doesn't line up")

                update = csv.reader(update_file)
                update_headers = next(update)
                if update_headers != self.voucher_update_properties:
                    raise AssertionError("Update doesn't line up")

                all_headers = dump_headers + update_headers
                if len(all_headers) != len(set(all_headers)):
                    raise AssertionError("There should be no duplicate headers")

                print "\nCombining spreadsheets and looking up vouchers"
                for dump_row, update_row in with_progress_bar(zip(dump, update)):
                    voucher = dict(
                        zip(dump_headers, dump_row) + zip(update_headers, update_row))
                    if voucher['Voucher ID (visible)'] != voucher['id']:
                        raise AssertionError("The spreadsheets don't line up! '{}' != '{}'".format(
                            voucher['Voucher ID (visible)'], voucher['id']
                        ))
                    yield voucher

    def get_voucher_from_list(self, possible_vouchers, voucher_dict):
        """Compare the voucher_dict to the possible vouchers and see if there's a clear match"""
        amount_fields = ['amount_approved', 'amount_eligible_for_redeemer', 'amount_fulfilled',
                         'amount_initial', 'amount_redeemed_per_chemist']

        def properties_match(voucher):
            get_value = voucher.get_case_property
            return (
                voucher_dict["Amount"] in [get_value(field) for field in amount_fields]
                and voucher_dict["Event Occur Date (Voucher Validation date)"] == get_value("date_fulfilled")
                and voucher.get_case_property("state") in ["fulfilled", "approved", "paid"]
            )

        def person_matches(voucher):
            person = get_person_case_from_voucher(self.domain, voucher.case_id)
            return person.get_case_property('person_id') == voucher_dict['PersonId']

        possible_vouchers = filter(properties_match, possible_vouchers)
        if len(possible_vouchers) != 1:
            # This will be slower, do only if necessary
            possible_vouchers = filter(person_matches, possible_vouchers)
        if len(possible_vouchers) == 1:
            return possible_vouchers[0]
        return None

    def make_voucher_update(self, voucher, voucher_dict):
        voucher_dict['amount'] = int(math.ceil(float(voucher_dict['amount'])))
        voucher_dict['paymentDate'] = date_parser.parse(voucher_dict['paymentDate'] or '2017-09-01')
        update = VoucherUpdate(
            id=voucher.case_id,
            **{
                k: v for k, v in voucher_dict.items()
                if k in self.voucher_update_properties
                and k not in ('id', 'EventID', 'Beneficiary ID')
            }
        )
        update._voucher = voucher
        return update

    @property
    @memoized
    def vouchers_by_readable_id(self):
        """returns a list of vouchers for each readable id"""
        vouchers = defaultdict(list)
        voucher_ids = self.accessor.get_case_ids_in_domain(CASE_TYPE_VOUCHER)
        for voucher in self.accessor.iter_cases(voucher_ids):
            vouchers[voucher.get_case_property(VOUCHER_ID)].append(voucher)
        return vouchers

    @staticmethod
    def _is_approved(voucher):
        return (
            voucher.get_case_property('state') in ('approved', 'paid',)
            or voucher.get_case_property('voucher_approval_status') in ('approved', 'partially_approved')
        )

    @staticmethod
    def _missing_key_properties(voucher):
        return not all(voucher.get_case_property(prop) for prop in [
            DATE_FULFILLED,
            DATE_APPROVED,
            FULFILLED_BY_ID,
            FULFILLED_BY_LOCATION_ID,
        ])

    def write_csv(self, filename, headers, rows):
        filename = "voucher_confirmations-{}.csv".format(filename)
        print "writing {} rows to {}".format(len(rows), filename)
        with open(filename, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    def _get_api_payload(self, voucher):
        try:
            return VoucherPayload.create_voucher_payload(voucher)
        except Exception:
            self.bad_payloads += 1
            return defaultdict(lambda: "PAYLOAD_ERROR")

    def log_voucher_updates(self, voucher_updates):
        headers = ['ReadableID'] + self.voucher_api_properties + self.voucher_update_properties

        def make_row(voucher_update):
            api_payload = self._get_api_payload(voucher_update._voucher)
            return [voucher_update._voucher.get_case_property(VOUCHER_ID)] + [
                api_payload[prop] for prop in self.voucher_api_properties
            ] + [
                voucher_update[prop] for prop in self.voucher_update_properties
                if prop not in ['EventID', 'Beneficiary ID']
            ]

        print "logging voucher updates"
        rows = map(make_row, with_progress_bar(voucher_updates))
        self.write_csv('updates', headers, rows)

    def log_dump_confirmations(self, voucher_dicts):
        headers = [
            'number possible vouchers',
            'voucher case_id',
            'voucher found',
            'confirmation status',
        ] + self.voucher_update_properties + self.voucher_dump_properties
        rows = [
            [
                voucher_dict['number possible vouchers'],
                voucher_dict['voucher case_id'],
                voucher_dict['voucher found'],
                voucher_dict['confirmation status'],
            ] + [
                voucher_dict[prop] for prop in self.voucher_update_properties + self.voucher_dump_properties
            ]
            for voucher_dict in voucher_dicts
        ]
        self.write_csv('confirmations', headers, rows)

    # def log_all_vouchers_in_domain(self, case_id_to_confirmation_status):
    #     voucher_ids = self.accessor.get_case_ids_in_domain(CASE_TYPE_VOUCHER)
    #     vouchers = list(self.accessor.iter_cases(voucher_ids))
    #     voucher_id_counts = Counter(v.get_case_property(VOUCHER_ID) for v in vouchers)
    #     headers = [
    #         "ReadableID",
    #         "URL",
    #         "state",
    #         "PaymentConfirmationStatus",
    #         "# Vouchers with ID",
    #     ]
    #     rows = [[
    #         voucher.get_case_property(VOUCHER_ID),
    #         'https://enikshay.in/a/enikshay/reports/case_data/{}'.format(voucher.case_id),
    #         voucher.get_case_property('state'),
    #         case_id_to_confirmation_status[voucher.case_id],
    #         voucher_id_counts[voucher.get_case_property(VOUCHER_ID)],
    #     ] for voucher in vouchers]
    #     self.write_csv('all_vouchers', headers, rows)

    def update_vouchers(self, voucher_updates):
        print "updating voucher cases"
        for chunk in chunked(with_progress_bar(voucher_updates), 100):
            updates = [
                (update.case_id, update.properties, False)
                for update in chunk
            ]
            if self.commit:
                bulk_update_cases(self.domain, updates)

    def reconcile_repeat_records(self, voucher_updates):
        """
        Mark updated records as "succeeded", all others as "cancelled"
        Delete duplicate records if any exist
        """
        print "Reconciling repeat records"
        chemist_voucher_repeater_id = 'be435d3f407bfb1016cc89ebbf8146b1'
        lab_voucher_repeater_id = 'be435d3f407bfb1016cc89ebbfc42a47'

        already_seen = set()
        updates_by_voucher_id = {update.id: update for update in voucher_updates}

        headers = ['record_id', 'voucher_id', 'status']
        rows = []

        get_db = (lambda: IterDB(RepeatRecord.get_db())) if self.commit else MagicMock
        with get_db() as iter_db:
            for repeater_id in [chemist_voucher_repeater_id, lab_voucher_repeater_id]:
                print "repeater {}".format(repeater_id)
                records = iter_repeat_records_by_domain(self.domain, repeater_id=repeater_id)
                record_count = get_repeat_record_count(self.domain, repeater_id=repeater_id)
                for record in with_progress_bar(records, record_count):
                    if record.payload_id in already_seen:
                        status = "deleted"
                        iter_db.delete(record)
                    elif record.payload_id in updates_by_voucher_id:
                        # add successful attempt
                        status = "succeeded"
                        attempt = RepeatRecordAttempt(
                            cancelled=False,
                            datetime=datetime.datetime.utcnow(),
                            failure_reason=None,
                            success_response="Paid offline via import_voucher_confirmations",
                            next_check=None,
                            succeeded=True,
                        )
                        record.add_attempt(attempt)
                        iter_db.save(record)
                    else:
                        # mark record as canceled
                        record.add_attempt(RepeatRecordAttempt(
                            cancelled=True,
                            datetime=datetime.datetime.utcnow(),
                            failure_reason="Cancelled during import_voucher_confirmations",
                            success_response=None,
                            next_check=None,
                            succeeded=False,
                        ))
                        iter_db.save(record)

                    already_seen.add(record.payload_id)
                    rows.append([record._id, record.payload_id, status])

        self.write_csv('repeat_records', headers, rows)
