"""
KYC Schema Registry — the single source of truth for the Individual KYC form.

This module encodes the CVL (CDSL Ventures Ltd.) "Know Your Client (KYC)
Application Form (For Individuals Only)" — the exact form in
samples/sample-kyc.pdf — as structured, strongly-typed metadata.

Design rules:
  * NOTHING outside this module defines KYC fields. The interview engine,
    validators, PDF filler, and frontend all consume this registry.
  * Field `id`s are stable contracts — later phases key coordinate maps and
    session state on them, so they must never be renamed casually.
  * `help_text` is written in plain language on purpose: it powers the
    product's "explain confusing fields" feature.

The registry is built once at import time and exposed through the
`kyc_registry` singleton.
"""

from app.domain.enums import FieldType, SectionType, ValidationType
from app.domain.models import FieldOption, KYCField, KYCForm, KYCSection


def _opts(*pairs: tuple[str, str]) -> tuple[FieldOption, ...]:
    """Small helper to build option tuples: _opts(("value", "Label"), ...)."""
    return tuple(FieldOption(value=v, label=l) for v, l in pairs)


# --------------------------------------------------------------------------- #
# Section A — Identity Details
# --------------------------------------------------------------------------- #

_IDENTITY_FIELDS: tuple[KYCField, ...] = (
    KYCField(
        id="full_name",
        display_name="Full Name",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="Name as on your PAN card",
        help_text=(
            "Your full name exactly as it appears on your supporting identity "
            "document (usually your PAN card). Spelling mismatches are the most "
            "common reason KYC applications get rejected."
        ),
        validation_type=ValidationType.NAME,
        example="Rahul Sharma",
    ),
    KYCField(
        id="father_spouse_name",
        display_name="Father's / Spouse's Name",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="Father's or spouse's full name",
        help_text=(
            "The full name of your father OR your spouse — either is accepted. "
            "Married applicants may use their spouse's name; everyone else "
            "typically uses their father's name."
        ),
        validation_type=ValidationType.NAME,
        example="Mahesh Sharma",
    ),
    KYCField(
        id="gender",
        display_name="Gender",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text="Select the gender recorded on your identity documents.",
        example="Male",
        options=_opts(("male", "Male"), ("female", "Female")),
    ),
    KYCField(
        id="marital_status",
        display_name="Marital Status",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text="Whether you are currently single or married.",
        example="Single",
        options=_opts(("single", "Single"), ("married", "Married")),
    ),
    KYCField(
        id="date_of_birth",
        display_name="Date of Birth",
        section=SectionType.IDENTITY,
        field_type=FieldType.DATE,
        required=True,
        placeholder="DD-MM-YYYY",
        help_text=(
            "Your date of birth as printed on your PAN card. It must match your "
            "identity documents exactly."
        ),
        validation_type=ValidationType.DOB,
        example="15-08-1999",
    ),
    KYCField(
        id="nationality",
        display_name="Nationality",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text=(
            "Your citizenship. Choose 'Other' only if you are not an Indian "
            "citizen — you will then need to specify the country."
        ),
        example="Indian",
        options=_opts(("indian", "Indian"), ("other", "Other")),
    ),
    KYCField(
        id="nationality_other",
        display_name="Nationality (if Other)",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Country of citizenship",
        help_text=(
            "Only needed if you selected 'Other' for nationality — write your "
            "country of citizenship."
        ),
        example="Nepalese",
    ),
    KYCField(
        id="residential_status",
        display_name="Residential Status",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text=(
            "'Resident Individual' means you live in India most of the year. "
            "'Non Resident' (NRI) means you are an Indian citizen living abroad. "
            "'Foreign National' means you are not an Indian citizen. NRIs and "
            "foreign nationals must attach a passport copy."
        ),
        example="Resident Individual",
        options=_opts(
            ("resident_individual", "Resident Individual"),
            ("non_resident", "Non Resident"),
            ("foreign_national", "Foreign National"),
        ),
    ),
    KYCField(
        id="pan",
        display_name="PAN",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="ABCDE1234F",
        help_text=(
            "Your 10-character Permanent Account Number issued by the Income Tax "
            "Department: 5 letters, 4 digits, 1 letter. You must enclose a "
            "self-attested copy of your PAN card with this form."
        ),
        validation_type=ValidationType.PAN,
        example="ABCDE1234F",
    ),
    KYCField(
        id="aadhaar",
        display_name="Aadhaar / UID Number",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="12-digit Aadhaar number",
        help_text=(
            "Your 12-digit Aadhaar (Unique Identification) number. Optional on "
            "this form, but providing it speeds up verification."
        ),
        validation_type=ValidationType.AADHAAR,
        example="123456789012",
    ),
    KYCField(
        id="poi_document",
        display_name="Proof of Identity Submitted",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text=(
            "Only for PAN-exempt cases: which identity document you are "
            "submitting instead of a PAN card. Most applicants have a PAN and "
            "can skip this."
        ),
        example="Passport",
        options=_opts(
            ("uid_aadhaar", "UID (Aadhaar)"),
            ("passport", "Passport"),
            ("voter_id", "Voter ID"),
            ("driving_licence", "Driving Licence"),
            ("others", "Others"),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Section B — Address Details
# --------------------------------------------------------------------------- #

_ADDRESS_FIELDS: tuple[KYCField, ...] = (
    KYCField(
        id="correspondence_address",
        display_name="Address for Correspondence",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="House/flat, street, area",
        help_text=(
            "The address where you currently receive mail. It must match the "
            "proof-of-address document you attach."
        ),
        example="Flat 302, MG Road, Pune, Maharashtra",
    ),
    KYCField(
        id="city",
        display_name="City / Town / Village",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="City, town, or village",
        example="Pune",
    ),
    KYCField(
        id="state",
        display_name="State",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="State or union territory",
        example="Maharashtra",
    ),
    KYCField(
        id="pincode",
        display_name="Pin Code",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="6-digit postal code",
        help_text="The 6-digit postal PIN code of your correspondence address.",
        validation_type=ValidationType.PINCODE,
        example="411001",
    ),
    KYCField(
        id="country",
        display_name="Country",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="Country of residence",
        example="India",
    ),
    KYCField(
        id="mobile",
        display_name="Mobile Number",
        section=SectionType.ADDRESS,
        field_type=FieldType.PHONE,
        required=True,
        placeholder="10-digit mobile number",
        help_text=(
            "Your 10-digit Indian mobile number. Banks send verification OTPs "
            "and account alerts here."
        ),
        validation_type=ValidationType.MOBILE,
        example="9876543210",
    ),
    KYCField(
        id="email",
        display_name="Email ID",
        section=SectionType.ADDRESS,
        field_type=FieldType.EMAIL,
        required=False,
        placeholder="you@example.com",
        help_text="Your email address for statements and communication.",
        validation_type=ValidationType.EMAIL,
        example="rahul.sharma@gmail.com",
    ),
    KYCField(
        id="telephone_office",
        display_name="Telephone (Office)",
        section=SectionType.ADDRESS,
        field_type=FieldType.PHONE,
        required=False,
        placeholder="Office landline with STD code",
        example="020-25501234",
    ),
    KYCField(
        id="telephone_residence",
        display_name="Telephone (Residence)",
        section=SectionType.ADDRESS,
        field_type=FieldType.PHONE,
        required=False,
        placeholder="Home landline with STD code",
        example="020-25505678",
    ),
    KYCField(
        id="poa_document",
        display_name="Proof of Address Document",
        section=SectionType.ADDRESS,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text=(
            "Which document you are attaching as proof of your correspondence "
            "address. Submit ANY ONE. Utility bills must be less than 3 months "
            "old."
        ),
        example="Passport",
        options=_opts(
            # The six OVDs every KRA form lists first, then the utility-bill
            # style proofs the CVL guidelines allow. Aadhaar / NREGA / NPR were
            # missing, so a CVL applicant had no way to name the document their
            # own form prints on its first three lines.
            ("aadhaar", "Aadhaar Card"),
            ("passport", "Passport"),
            ("voter_id", "Voter Identity Card"),
            ("driving_licence", "Driving Licence"),
            ("nrega_job_card", "NREGA Job Card"),
            ("npr_letter", "NPR Letter"),
            ("ration_card", "Ration Card"),
            ("registered_lease", "Registered Lease / Sale Agreement of Residence"),
            ("bank_statement", "Latest Bank A/c Statement / Passbook"),
            ("telephone_bill", "Latest Telephone Bill (only Land Line)"),
            ("electricity_bill", "Latest Electricity Bill"),
            ("gas_bill", "Latest Gas Bill"),
            ("others", "Others"),
        ),
    ),
    KYCField(
        id="permanent_address",
        display_name="Permanent Address",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Leave blank if same as correspondence address",
        help_text=(
            "Only needed if your permanent address is different from your "
            "correspondence address. Mandatory for Non-Resident applicants "
            "(overseas address)."
        ),
        example="H.No. 12, Civil Lines, Nagpur, Maharashtra",
    ),
    KYCField(
        id="permanent_pincode",
        display_name="Permanent Address Pin Code",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="6-digit postal code",
        help_text="Pin code of your permanent address, if different from above.",
        validation_type=ValidationType.PINCODE,
        example="440001",
    ),
)

# --------------------------------------------------------------------------- #
# Section C — Other Details
# --------------------------------------------------------------------------- #

_OTHER_FIELDS: tuple[KYCField, ...] = (
    KYCField(
        id="gross_annual_income",
        display_name="Gross Annual Income",
        section=SectionType.OTHER,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text=(
            "Your total yearly income before taxes, as a range — you don't need "
            "the exact figure. 1 Lac = ₹1,00,000. For example, a ₹12,00,000 "
            "yearly salary falls in the '10-25 Lac' band."
        ),
        example="10-25 Lac",
        options=_opts(
            ("below_1l", "Below 1 Lac"),
            ("1_5l", "1-5 Lac"),
            ("5_10l", "5-10 Lac"),
            ("10_25l", "10-25 Lac"),
            ("above_25l", "> 25 Lacs"),
        ),
    ),
    KYCField(
        id="net_worth",
        display_name="Net Worth (₹)",
        section=SectionType.OTHER,
        field_type=FieldType.NUMBER,
        required=False,
        placeholder="Total assets minus liabilities, in rupees",
        help_text=(
            "An alternative to declaring your income range: your net worth "
            "(everything you own minus everything you owe). If provided, it must "
            "not be older than 1 year. Most salaried applicants simply declare "
            "the income range instead."
        ),
        validation_type=ValidationType.NUMBER,
        example="2500000",
    ),
    KYCField(
        id="net_worth_date",
        display_name="Net Worth As On Date",
        section=SectionType.OTHER,
        field_type=FieldType.DATE,
        required=False,
        placeholder="DD-MM-YYYY",
        help_text=(
            "The date your net worth was calculated. Only needed if you declared "
            "a net worth figure; must be within the last year."
        ),
        validation_type=ValidationType.DATE,
        example="31-03-2026",
    ),
    KYCField(
        id="occupation",
        display_name="Occupation",
        section=SectionType.OTHER,
        field_type=FieldType.SINGLE_CHOICE,
        required=True,
        help_text=(
            "What you do for a living. Pick the closest match — e.g. a software "
            "engineer at a private company is 'Private Sector Service'; "
            "'Professional' means self-employed professionals like doctors, "
            "lawyers, or CAs."
        ),
        example="Private Sector Service",
        options=_opts(
            ("private_sector", "Private Sector Service"),
            ("public_sector", "Public Sector"),
            ("government_service", "Government Service"),
            ("business", "Business"),
            ("professional", "Professional"),
            ("agriculturist", "Agriculturist"),
            ("retired", "Retired"),
            ("housewife", "Housewife"),
            ("student", "Student"),
            ("forex_dealer", "Forex Dealer"),
            ("others", "Others"),
        ),
    ),
    KYCField(
        id="is_pep",
        display_name="Politically Exposed Person (PEP)",
        section=SectionType.OTHER,
        field_type=FieldType.BOOLEAN,
        required=True,
        help_text=(
            "A Politically Exposed Person is someone holding (or who recently "
            "held) a prominent public position — e.g. politicians, senior "
            "government or military officials, heads of state-owned companies. "
            "For almost everyone the honest answer is 'No'."
        ),
        example="No",
    ),
    KYCField(
        id="is_pep_related",
        display_name="Related to a Politically Exposed Person",
        section=SectionType.OTHER,
        field_type=FieldType.BOOLEAN,
        required=True,
        help_text=(
            "Whether a close family member or associate of yours is a "
            "Politically Exposed Person (see the PEP explanation). Again, for "
            "most applicants this is 'No'."
        ),
        example="No",
    ),
    KYCField(
        id="other_information",
        display_name="Any Other Information",
        section=SectionType.OTHER,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Anything else the bank should know (usually blank)",
        help_text="Optional free-text remarks. Almost always left blank.",
        example="",
    ),
)

# --------------------------------------------------------------------------- #
# Declaration
# --------------------------------------------------------------------------- #

_DECLARATION_FIELDS: tuple[KYCField, ...] = (
    # Image assets. Both are required=False HERE on purpose: only the ACTIVE
    # primary form decides whether they are needed, by adding their ids to the
    # session's required set (see DocumentIntelligenceService). A form with no
    # photo box therefore never triggers the question at all.
    KYCField(
        id="applicant_photo",
        display_name="Passport-size Photograph",
        section=SectionType.DECLARATION,
        field_type=FieldType.ASSET,
        required=False,
        help_text=(
            "A recent passport-size photograph of you. Upload a JPG or PNG up "
            "to 5 MB — it is placed inside the photo box printed on your form."
        ),
        example="photo.jpg",
    ),
    KYCField(
        id="applicant_signature",
        display_name="Applicant Signature",
        section=SectionType.DECLARATION,
        field_type=FieldType.ASSET,
        required=False,
        help_text=(
            "A photo or scan of your signature on plain paper. Upload a JPG or "
            "PNG up to 2 MB — it is placed on your form's signature line."
        ),
        example="signature.png",
    ),
    KYCField(
        id="declaration_place",
        display_name="Place",
        section=SectionType.DECLARATION,
        field_type=FieldType.TEXT,
        required=True,
        placeholder="City where you are signing the form",
        help_text="The city/town where you are signing this declaration.",
        # A place, not merely a word: without this an answer of "Yes" — meant
        # for the YES/NO row printed a few lines above on the SBI form — passed
        # every letters-only rule and was printed as the place of signing.
        validation_type=ValidationType.PLACE,
        example="Pune",
    ),
    KYCField(
        id="declaration_date",
        display_name="Date",
        section=SectionType.DECLARATION,
        field_type=FieldType.DATE,
        required=True,
        placeholder="DD-MM-YYYY",
        help_text="The date on which you sign the form.",
        validation_type=ValidationType.DATE,
        example="15-07-2026",
    ),
)

# --------------------------------------------------------------------------- #
# Fields some bank forms capture that the base CVL form does not. All are
# required=False here: a field only becomes mandatory when a form's schema
# lists it in `required_session_fields`, so adding them cannot change any
# existing form's progress or interview.
# --------------------------------------------------------------------------- #

_SUPPLEMENTARY_FIELDS: tuple[KYCField, ...] = (
    KYCField(
        id="account_number",
        display_name="Account Number",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Your bank account number",
        help_text="The account this KYC update applies to, as printed on your passbook or statement.",
        example="30123456789",
    ),
    KYCField(
        id="ckycr_number",
        display_name="CKYCR Number",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="14-digit CKYC identifier",
        help_text=(
            "Your Central KYC Registry number, issued once your KYC is registered "
            "centrally. It appears on earlier KYC acknowledgements."
        ),
        example="12345678901234",
    ),
    KYCField(
        id="mother_name",
        display_name="Mother's Name",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Your mother's full name",
        help_text="Your mother's full name, as recorded on your identity documents.",
        validation_type=ValidationType.NAME,
        example="Sunita Sharma",
    ),
    KYCField(
        id="spouse_name",
        display_name="Spouse's Name",
        section=SectionType.IDENTITY,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Your spouse's full name (if married)",
        help_text="Leave blank if you are not married.",
        validation_type=ValidationType.NAME,
        example="Anjali Sharma",
    ),
    KYCField(
        id="religion",
        display_name="Religion",
        section=SectionType.OTHER,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Optional",
        help_text="Collected by some banks for statutory reporting. Optional.",
        example="Hindu",
    ),
    KYCField(
        id="category",
        display_name="Category",
        section=SectionType.OTHER,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text="Social category as recorded by the bank (General/OBC/SC/ST).",
        example="General",
        options=_opts(("general", "General"), ("obc", "OBC"),
                      ("sc", "SC"), ("st", "ST")),
    ),
    KYCField(
        id="monthly_income",
        display_name="Monthly Income",
        section=SectionType.OTHER,
        field_type=FieldType.NUMBER,
        required=False,
        placeholder="Monthly income in rupees",
        help_text=(
            "Your income per MONTH in rupees. Some forms ask for a monthly figure "
            "rather than an annual band — this is kept separate so the two are "
            "never converted into one another."
        ),
        validation_type=ValidationType.NUMBER,
        example="45000",
    ),
    KYCField(
        id="application_type",
        display_name="Application Type",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text=(
            "Whether this is a NEW KYC registration or an UPDATE to a record "
            "you already have. An update needs your existing KYC number."
        ),
        example="New",
        options=_opts(("new", "New"), ("update", "Update")),
    ),
    KYCField(
        id="kyc_mode",
        display_name="KYC Mode",
        section=SectionType.IDENTITY,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text=(
            "How this KYC is being carried out. Choose Normal unless you are "
            "completing it online through one of the digital routes."
        ),
        example="Normal",
        options=_opts(
            ("normal", "Normal"),
            ("ekyc_otp", "EKYC OTP"),
            ("ekyc_biometric", "EKYC Biometric"),
            ("online_kyc", "Online KYC"),
            ("offline_ekyc", "Offline EKYC"),
            ("digilocker", "Digilocker"),
        ),
    ),
    KYCField(
        id="poa_document_number",
        display_name="Proof of Address — Identification Number",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Number printed on the proof you selected",
        help_text=(
            "The identification number of the address proof you chose, as "
            "printed on that document."
        ),
        example="X1234567",
    ),
    KYCField(
        id="address_type",
        display_name="Address Type",
        section=SectionType.ADDRESS,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text="What this address is used for, as the form classifies it.",
        example="Residential",
        options=_opts(
            ("residential_business", "Residential / Business"),
            ("residential", "Residential"),
            ("business", "Business"),
            ("registered_office", "Registered Office"),
            ("unspecified", "Unspecified"),
        ),
    ),
    KYCField(
        id="correspondence_same_as_permanent",
        display_name="Correspondence Address Same as Current / Permanent",
        section=SectionType.ADDRESS,
        field_type=FieldType.SINGLE_CHOICE,
        required=False,
        help_text=(
            "Say Yes if letters should go to the same address you gave above. "
            "Answering Yes ticks the form's own 'same as' box, so the address "
            "is never written out twice."
        ),
        example="Yes",
        options=_opts(("yes", "Yes"), ("no", "No")),
    ),
    KYCField(
        id="district",
        display_name="District",
        section=SectionType.ADDRESS,
        field_type=FieldType.TEXT,
        required=False,
        placeholder="Revenue district of your address",
        help_text=(
            "The district your address falls in, which some forms record "
            "separately from the city or town."
        ),
        example="Nashik",
    ),
    KYCField(
        id="sources_of_funds",
        display_name="Sources of Funds",
        section=SectionType.OTHER,
        field_type=FieldType.MULTI_CHOICE,
        required=False,
        placeholder="Salary, Business Income, Agriculture, …",
        help_text=(
            "Where the money in this account comes from. Choose every one that "
            "applies — you can name more than one, e.g. 'Salary and Pension'."
        ),
        example="Salary",
        options=_opts(
            ("salary", "Salary"),
            ("business_income", "Business Income"),
            ("agriculture", "Agriculture"),
            ("investment_income", "Investment Income"),
            ("pension", "Pension"),
            ("others", "Others"),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Form assembly
# --------------------------------------------------------------------------- #

_KYC_FORM = KYCForm(
    id="cvl_kyc_individual",
    title="Know Your Client (KYC) Application Form (For Individuals Only)",
    description=(
        "CVL KYC application form for individual bank/investment customers. "
        "Fill in English and in BLOCK LETTERS with black ink."
    ),
    version="1.0.0",
    sections=(
        KYCSection(
            id=SectionType.IDENTITY,
            title="A. Identity Details",
            description="Who you are: name, birth date, nationality, PAN.",
            order=1,
            fields=_IDENTITY_FIELDS,
        ),
        KYCSection(
            id=SectionType.ADDRESS,
            title="B. Address Details",
            description="Where you live and how to contact you.",
            order=2,
            fields=_ADDRESS_FIELDS,
        ),
        KYCSection(
            id=SectionType.OTHER,
            title="C. Other Details",
            description="Income, occupation, and politically-exposed-person status.",
            order=3,
            fields=_OTHER_FIELDS,
        ),
        KYCSection(
            id=SectionType.DECLARATION,
            title="Declaration",
            description="Where and when you sign the form.",
            order=4,
            fields=_DECLARATION_FIELDS + _SUPPLEMENTARY_FIELDS,
        ),
    ),
)


class KYCSchemaRegistry:
    """
    Read-only registry over the KYC form definition.

    Builds fast lookup indexes once at construction and exposes typed accessors.
    All downstream consumers (FormService today; validators, interview engine,
    and PDF filler in later phases) go through this class — never through the
    private module-level tuples above.
    """

    def __init__(self, form: KYCForm) -> None:
        self._form = form
        # Index fields by id for O(1) lookup; also enforces id uniqueness.
        self._fields_by_id: dict[str, KYCField] = {}
        for section in form.sections:
            for field in section.fields:
                if field.id in self._fields_by_id:
                    raise ValueError(f"Duplicate KYC field id: {field.id!r}")
                self._fields_by_id[field.id] = field

    @property
    def form(self) -> KYCForm:
        """The complete form definition."""
        return self._form

    @property
    def sections(self) -> tuple[KYCSection, ...]:
        """All sections in display order."""
        return self._form.sections

    def all_fields(self) -> tuple[KYCField, ...]:
        """Every field on the form, in form order."""
        return tuple(self._fields_by_id.values())

    def get_field(self, field_id: str) -> KYCField | None:
        """Look up one field by id; None if it doesn't exist."""
        return self._fields_by_id.get(field_id)

    def required_fields(self) -> tuple[KYCField, ...]:
        """Only the mandatory fields, in form order."""
        return tuple(f for f in self._fields_by_id.values() if f.required)

    def fields_by_section(self, section: SectionType) -> tuple[KYCField, ...]:
        """All fields belonging to the given section, in form order."""
        return tuple(f for f in self._fields_by_id.values() if f.section == section)


# Singleton instance — built once at import; the single source of truth.
kyc_registry = KYCSchemaRegistry(_KYC_FORM)
