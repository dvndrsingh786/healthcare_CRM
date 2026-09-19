from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, EmailStr, Field, StringConstraints, model_validator

from app.schemas import Name, Out, Page, Phone, StrictModel

# Field classification. SENSITIVE fields are only returned to roles with patients:read_sensitive
# and are redacted from logs. The serializer in service.py uses this list as its allow-list.
SENSITIVE_FIELDS = ("mrn", "date_of_birth", "address_line1", "address_line2", "city", "postcode", "country")
PERSONAL_FIELDS = ("legal_first_name", "legal_last_name", "preferred_name", "email", "phone")


def check_date_of_birth(value: date):
    if value > date.today():
        raise ValueError("Date of birth cannot be in the future.")
    if value < date(1900, 1, 1):
        raise ValueError("Date of birth must be on or after 1900-01-01.")
    return value


# Letters (any alphabet), with spaces, apostrophes, hyphens and dots between them ("Mary-Jane",
# "O'Neil", "St. John"). Digits and other symbols are rejected.
PersonName = Annotated[str, StringConstraints(min_length=1, max_length=100,
                                              pattern=r"^[^\W\d_]+([ '’.-]+[^\W\d_]+)*\.?$")]
DateOfBirth = Annotated[date, AfterValidator(check_date_of_birth)]
Mrn = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{3,40}$")]
Postcode = Annotated[str, StringConstraints(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9 -]+$")]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
PatientStatus = Literal["ACTIVE", "INACTIVE", "ARCHIVED"]


def reject_nulls(model, fields):
    """PATCH bodies: leaving a field out means "no change", but a required field cannot be
    cleared by sending null. Checked here so the client gets a clear 422 for that field."""
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} cannot be empty.")
    return model


class EmergencyContactIn(StrictModel):
    name: Name
    relationship: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    phone: Phone | None = None
    email: EmailStr | None = None
    priority: int = Field(1, ge=1, le=9)
    is_next_of_kin: bool = False

    @model_validator(mode="after")
    def reachable(self):
        if self.phone is None and self.email is None:
            raise ValueError("Give at least a phone number or an email address.")
        return self


class EmergencyContactUpdate(StrictModel):
    name: Name | None = None
    relationship: Annotated[str, StringConstraints(min_length=1, max_length=60)] | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    priority: int | None = Field(None, ge=1, le=9)
    is_next_of_kin: bool | None = None

    @model_validator(mode="after")
    def required_fields_not_cleared(self):
        return reject_nulls(self, ("name", "relationship", "priority", "is_next_of_kin"))


class EmergencyContactOut(Out):
    id: UUID
    name: str
    relationship: str
    phone: str | None
    email: str | None
    priority: int
    is_next_of_kin: bool
    updated_at: datetime


class PatientCreate(StrictModel):
    legal_first_name: PersonName
    legal_last_name: PersonName
    preferred_name: PersonName | None = None
    date_of_birth: DateOfBirth
    mrn: Mrn | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    address_line1: Annotated[str, StringConstraints(max_length=200)] | None = None
    address_line2: Annotated[str, StringConstraints(max_length=200)] | None = None
    city: Annotated[str, StringConstraints(max_length=100)] | None = None
    postcode: Postcode | None = None
    country: Country = "GB"
    preferred_language: Language = "en"
    contact_by_email: bool = True
    contact_by_sms: bool = False
    contact_by_push: bool = True
    emergency_contacts: list[EmergencyContactIn] = Field(default_factory=list, max_length=5)
    # A patient with the same name and date of birth already exists -> 409 POSSIBLE_DUPLICATE.
    # After checking it really is a different person, resend with this set to true.
    confirm_not_duplicate: bool = False

    model_config = {"json_schema_extra": {"examples": [{
        "legal_first_name": "Margaret", "legal_last_name": "Okafor", "preferred_name": "Maggie",
        "date_of_birth": "1948-03-14", "mrn": "NF-100245", "phone": "+44 7700 900456",
        "email": "maggie.okafor@example.com", "address_line1": "12 Elm Road", "city": "Leeds",
        "postcode": "LS1 4AB", "contact_by_sms": True,
        "emergency_contacts": [{"name": "David Okafor", "relationship": "Son", "phone": "+44 7700 900789",
                                "is_next_of_kin": True}],
    }]}}


class PatientUpdate(StrictModel):
    # The version you read. If someone else changed the patient since, you get 409 VERSION_CONFLICT.
    version: int = Field(ge=1)
    legal_first_name: PersonName | None = None
    legal_last_name: PersonName | None = None
    preferred_name: PersonName | None = None
    date_of_birth: DateOfBirth | None = None
    mrn: Mrn | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    address_line1: Annotated[str, StringConstraints(max_length=200)] | None = None
    address_line2: Annotated[str, StringConstraints(max_length=200)] | None = None
    city: Annotated[str, StringConstraints(max_length=100)] | None = None
    postcode: Postcode | None = None
    country: Country | None = None
    preferred_language: Language | None = None
    contact_by_email: bool | None = None
    contact_by_sms: bool | None = None
    contact_by_push: bool | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None

    @model_validator(mode="after")
    def required_fields_not_cleared(self):
        return reject_nulls(self, ("legal_first_name", "legal_last_name", "date_of_birth", "country",
                                   "preferred_language", "contact_by_email", "contact_by_sms",
                                   "contact_by_push", "status"))


class ArchiveRequest(StrictModel):
    reason: Annotated[str, StringConstraints(min_length=3, max_length=255)]


class AppAccountCreate(StrictModel):
    email: EmailStr


class PatientOut(Out):
    """Fields marked (sensitive) are null unless the caller has patients:read_sensitive;
    `sensitive_fields_hidden` tells the client whether that happened."""
    id: UUID
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None
    email: str | None
    phone: str | None
    preferred_language: str
    contact_by_email: bool
    contact_by_sms: bool
    contact_by_push: bool
    status: PatientStatus
    has_app_account: bool
    version: int
    created_at: datetime
    updated_at: datetime
    sensitive_fields_hidden: bool
    mrn: str | None = Field(None, description="(sensitive)")
    date_of_birth: date | None = Field(None, description="(sensitive)")
    address_line1: str | None = Field(None, description="(sensitive)")
    address_line2: str | None = Field(None, description="(sensitive)")
    city: str | None = Field(None, description="(sensitive)")
    postcode: str | None = Field(None, description="(sensitive)")
    country: str | None = Field(None, description="(sensitive)")
    archived_at: datetime | None = None


class AppProfileOut(Out):
    """The patient's own record, as shown in the patient app. It is their own data, so the
    identity and address fields are included; internal fields (MRN, status, audit) are not."""
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None
    date_of_birth: date
    email: str | None
    phone: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    postcode: str | None
    country: str
    preferred_language: str
    contact_by_email: bool
    contact_by_sms: bool
    contact_by_push: bool
    updated_at: datetime


class AppProfileUpdate(StrictModel):
    """What a patient may change themselves. Legal name, date of birth and address are changed
    by staff, who check them first."""
    preferred_name: PersonName | None = None
    phone: Phone | None = None
    preferred_language: Language | None = None
    contact_by_email: bool | None = None
    contact_by_sms: bool | None = None
    contact_by_push: bool | None = None

    @model_validator(mode="after")
    def required_fields_not_cleared(self):
        return reject_nulls(self, ("preferred_language", "contact_by_email", "contact_by_sms", "contact_by_push"))


class PatientList(Page):
    data: list[PatientOut]


class AssignmentCreate(StrictModel):
    staff_user_id: UUID | None = None
    team_id: UUID | None = None
    assignment_type: Literal["PRIMARY", "SECONDARY", "TEAM"]
    starts_on: date | None = None

    @model_validator(mode="after")
    def one_target(self):
        if (self.staff_user_id is None) == (self.team_id is None):
            raise ValueError("Give exactly one of staff_user_id or team_id.")
        if self.team_id is not None and self.assignment_type != "TEAM":
            raise ValueError("Team assignments must use assignment_type TEAM.")
        if self.staff_user_id is not None and self.assignment_type == "TEAM":
            raise ValueError("Staff assignments must be PRIMARY or SECONDARY.")
        return self


class AssignmentOut(Out):
    id: UUID
    patient_id: UUID
    staff_user_id: UUID | None
    staff_display_name: str | None
    team_id: UUID | None
    team_name: str | None
    assignment_type: str
    starts_on: date
    ends_on: date | None
    active: bool
    created_at: datetime
    ended_at: datetime | None


class CaseloadEntry(Out):
    patient_id: UUID
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None
    status: PatientStatus
    assignment_type: str
    via_team: str | None
    updated_at: datetime


class Caseload(Page):
    data: list[CaseloadEntry]
