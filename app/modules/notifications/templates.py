"""Message templates.

Healthcare rule: SMS, push and email previews say only THAT something happened and point to
the app. They never contain diagnoses, appointment types, staff names, locations or times, because
lock screens, shared inboxes and SMS logs are not private. The app shows the details after login.

`transactional` messages concern care the patient is already receiving (their own appointment
changing). Whether they are sent despite a channel opt-out is an organisation policy
(settings.notifications.transactional_ignores_opt_out). Other messages always respect opt-outs.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    subject: str
    text: str
    transactional: bool


TEMPLATES = {
    "appointment_booked": Template(
        "You have a new appointment", "{org} has booked an appointment for you. Open the app to see the details.",
        transactional=True),
    "appointment_rescheduled": Template(
        "Your appointment has changed", "{org} has changed one of your appointments. Open the app to see the "
        "new details.", transactional=True),
    "appointment_cancelled": Template(
        "Your appointment has been cancelled", "{org} has cancelled one of your appointments. Open the app for "
        "details.", transactional=True),
    "appointment_reminder": Template(
        "Appointment reminder", "Reminder: you have an upcoming appointment with {org}. Open the app to see the "
        "details.", transactional=True),
    "new_message": Template(
        "You have a new message", "You have a new message from {org}. Open the app to read it.",
        transactional=True),
    "document_available": Template(
        "A new document is available", "{org} has shared a document with you. Open the app to view it.",
        transactional=True),
    "service_update": Template(
        "News from {org}", "{org} has an update for you. Open the app to read it.", transactional=False),
}


def render(template_key, organisation_name):
    template = TEMPLATES[template_key]
    return (template.subject.format(org=organisation_name), template.text.format(org=organisation_name))
