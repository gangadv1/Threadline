"""
mock_data.py
============
SHARE THIS FILE WITH YOUR TEAM RIGHT NOW.

Role 3 (Backend) and Role 4 (Frontend) do NOT need to wait for you to
finish the real OpenAI integration or get an API key working. They can
import `MOCK_EXTRACTION_RESULT` today and build their database models /
UI screens against it, because it matches the exact same schema
(schemas.ExtractionResult) that the real extractor.py will eventually return.

Once your real extractor is working, nobody else's code needs to change —
you just swap the mock for the real function call.
"""

from schemas import ExtractionResult, Task, Priority, Category

MOCK_EXTRACTION_RESULT = ExtractionResult(
    extraction_notes="Deadline for course bidding was not explicitly stated; left null.",
    tasks=[
        Task(
            task_name="Obtain Valid Passport",
            description="Ensure your passport is valid for at least 6 months beyond your intended stay.",
            deadline=None,
            deadline_is_explicit=False,
            dependencies=[],
            required_documents=["Existing passport (if renewing)"],
            category=Category.VISA_IMMIGRATION,
            priority=Priority.HIGH,
            source_snippet=None,
        ),
        Task(
            task_name="Apply for Student's Pass",
            description="Submit your Student's Pass application via ICA within 2 weeks of receiving your IPA letter.",
            deadline="2026-09-19",
            deadline_is_explicit=True,
            dependencies=["Obtain Valid Passport"],
            required_documents=["Passport", "Passport-sized photo", "IPA letter"],
            category=Category.VISA_IMMIGRATION,
            priority=Priority.HIGH,
            source_snippet="apply for their Student's Pass through ICA within 2 weeks",
        ),
        Task(
            task_name="Pay Housing Deposit",
            description="Pay the $500 hostel housing deposit before rooms are released.",
            deadline="2026-08-15",
            deadline_is_explicit=True,
            dependencies=[],
            required_documents=["Payment receipt"],
            category=Category.HOUSING,
            priority=Priority.HIGH,
            source_snippet="housing deposit of $500 to be paid by 15 August 2026",
        ),
        Task(
            task_name="Settle Tuition Fees",
            description="Pay tuition fees to confirm matriculation before course bidding opens.",
            deadline=None,
            deadline_is_explicit=False,
            dependencies=[],
            required_documents=["Fee payment confirmation"],
            category=Category.FINANCE_PAYMENT,
            priority=Priority.HIGH,
            source_snippet="only happens once tuition fees are settled",
        ),
        Task(
            task_name="Bid for Courses",
            description="Participate in course bidding once matriculation is confirmed.",
            deadline=None,
            deadline_is_explicit=False,
            dependencies=["Settle Tuition Fees"],
            required_documents=[],
            category=Category.ACADEMIC_ENROLLMENT,
            priority=Priority.MEDIUM,
            source_snippet="Course bidding opens after your matriculation is confirmed",
        ),
    ],
)


if __name__ == "__main__":
    # Run `python mock_data.py` to see the exact JSON shape your teammates
    # will receive from the real /extract endpoint.
    print(MOCK_EXTRACTION_RESULT.model_dump_json(indent=2))
