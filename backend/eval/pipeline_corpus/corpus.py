# ruff: noqa: E501
"""~120 synthetic threads modelled on common ATS and company templates.

Companies, people and the student ("Sam") are invented. Senders are the real ATS domains or
.example. Snippets include the boilerplate Gmail puts first. Expectations are the truth a user
would want, not what the pipeline currently does.
"""

from eval.pipeline_corpus.model import Case, Msg

GH = "no-reply@us.greenhouse-mail.io"
LEVER = "no-reply@hire.lever.co"
ASHBY = "no-reply@ashbyhq.com"
ME = "sam.student@mail.example"
INT, OA, CONF, REJ, OFF = "interview", "online_assessment", "confirmation", "rejection", "offer"
APPLIED = "applied"
REJECTED = "rejected"
SWE = "Software Engineer Intern"


def m(
    name: str,
    addr: str,
    subj: str,
    snip: str,
    day: int,
    *,
    user: bool = False,
    tail: str = "",
    draft: bool = False,
) -> Msg:
    return Msg(name, addr, subj, snip, day, user, draft, tail)


def app(
    cid: str,
    fam: str,
    msgs: list[Msg],
    label: str,
    status: str,
    company: str | None,
    role: str | None,
    group: str | None = None,
) -> Case:
    return Case(cid, fam, tuple(msgs), "application", label, status, company, role, group)


def rec(cid: str, fam: str, msgs: list[Msg]) -> Case:
    return Case(cid, fam, tuple(msgs), "recruiter", "recruiter_message")


def noise(cid: str, fam: str, msgs: list[Msg]) -> Case:
    return Case(cid, fam, tuple(msgs), "noise")


def _greenhouse() -> list[Case]:
    cs: list[Case] = []
    n = "Acme Talent Acquisition"
    cs.append(
        app(
            "gh-conf-1",
            "greenhouse",
            [
                m(
                    n,
                    GH,
                    "Thank you for applying to Acme",
                    "Hi Sam, Thank you for applying to the Software Engineer Intern position at Acme. We have received your application and our team will review it carefully.",
                    20,
                )
            ],
            CONF,
            APPLIED,
            "Acme",
            SWE,
        )
    )
    cs.append(
        app(
            "gh-conf-2",
            "greenhouse",
            [
                m(
                    "Globex Recruiting",
                    GH,
                    "Your application to Data Science Intern at Globex",
                    "[image: Globex logo] Hi Sam, thanks for your interest in Globex! We wanted to let you know that we received your application for Data Science Intern and are excited to learn more about you.",
                    19,
                )
            ],
            CONF,
            APPLIED,
            "Globex",
            "Data Science Intern",
        )
    )
    cs.append(
        app(
            "gh-conf-3",
            "greenhouse",
            [
                m(
                    "Initech",
                    GH,
                    "Thank you for your application!",
                    "Hi Sam, Thank you for your application to Initech. We're reviewing your qualifications for the Platform Engineering Intern role and will be in touch if there is a match. Best, The Initech Team",
                    18,
                )
            ],
            CONF,
            APPLIED,
            "Initech",
            "Platform Engineering Intern",
        )
    )
    cs.append(
        app(
            "gh-conf-4",
            "greenhouse",
            [
                m(
                    "Umbrella Labs Careers",
                    GH,
                    "We received your application",
                    "Dear Candidate, Please do not reply to this email. This message was sent to sam.student@mail.example because you applied for Machine Learning Intern at Umbrella Labs.",
                    17,
                    tail=" We will review your application.",
                )
            ],
            CONF,
            APPLIED,
            "Umbrella Labs",
            "Machine Learning Intern",
        )
    )
    cs.append(
        app(
            "gh-conf-5",
            "greenhouse",
            [
                m(
                    "Hooli",
                    GH,
                    "Application Received - Hooli",
                    "View this email in your browser Hi Sam, Thanks for applying to Hooli. We have received your application for Backend Intern and will review it shortly. If your background is a match we will reach out.",
                    16,
                    tail="",
                )
            ],
            CONF,
            APPLIED,
            "Hooli",
            "Backend Intern",
        )
    )
    cs.append(
        app(
            "gh-rej-1",
            "greenhouse",
            [
                m(
                    n,
                    GH,
                    "Update on your Acme application",
                    "Hi Sam, Thank you for taking the time to apply for the Software Engineer Intern role at Acme. After careful consideration, we have decided to move forward with other candidates.",
                    6,
                )
            ],
            REJ,
            REJECTED,
            "Acme",
            SWE,
        )
    )
    cs.append(
        app(
            "gh-rej-2",
            "greenhouse",
            [
                m(
                    "Soylent",
                    GH,
                    "Your application with Soylent",
                    "Hi Sam, Thank you for your interest in Soylent and for the time you spent applying to the Product Design Intern position. We received applications from many talented candidates and ",
                    7,
                    tail="unfortunately we will not be moving forward with your application at this time.",
                )
            ],
            REJ,
            REJECTED,
            "Soylent",
            "Product Design Intern",
        )
    )
    cs.append(
        app(
            "gh-rej-3",
            "greenhouse",
            [
                m(
                    "Stark Dynamics",
                    GH,
                    "An update on your application",
                    "Dear Sam, Thank you for giving us the opportunity to consider your application for Embedded Software Intern. We regret to inform you that we are unable to move forward with your candidacy.",
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Stark Dynamics",
            "Embedded Software Intern",
        )
    )
    cs.append(
        app(
            "gh-rej-4",
            "greenhouse",
            [
                m(
                    "Wayne Systems",
                    GH,
                    "Update on your application to Wayne Systems",
                    "Hi Sam, Thank you for your interest in the Security Intern role at Wayne Systems. We appreciate the time you invested. Unfortunately, after reviewing your background, we won't be moving forward.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Wayne Systems",
            "Security Intern",
        )
    )
    cs.append(
        app(
            "gh-int-1",
            "greenhouse",
            [
                m(
                    n,
                    GH,
                    "Next steps with Acme",
                    "Hi Sam, Thank you for your interest in Acme. We were impressed with your application and would like to schedule an interview with you for the Software Engineer Intern position.",
                    10,
                )
            ],
            INT,
            "interview",
            "Acme",
            SWE,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "gh-int-2",
            "greenhouse",
            [
                m(
                    "Cyberdyne",
                    GH,
                    "Interview invitation - Cyberdyne",
                    "Hi Sam, Thanks for applying to Cyberdyne! We'd love to chat about the Robotics Intern role. Please use the link below to pick a time that works for you for a 30 minute video call.",
                    9,
                )
            ],
            INT,
            "interview",
            "Cyberdyne",
            "Robotics Intern",
        )
    )
    cs.append(
        app(
            "gh-int-3",
            "greenhouse",
            [
                m(
                    "Vandelay Industries",
                    GH,
                    "Interview availability",
                    "Hi Sam, Thank you for applying to Vandelay Industries. Please share your availability for a call next week so we can talk about the Logistics Software Intern role.",
                    8,
                )
            ],
            INT,
            "interview",
            "Vandelay Industries",
            "Logistics Software Intern",
        )
    )
    cs.append(
        app(
            "gh-off-1",
            "greenhouse",
            [
                m(
                    "Pied Piper",
                    GH,
                    "Congratulations!",
                    "Hi Sam, Congratulations! We are pleased to offer you the Compression Research Intern position at Pied Piper. Your offer letter is attached; please review and sign by Friday.",
                    2,
                )
            ],
            OFF,
            "offer",
            "Pied Piper",
            "Compression Research Intern",
        )
    )
    cs.append(
        app(
            "gh-off-2",
            "greenhouse",
            [
                m(
                    "Aperture Science",
                    GH,
                    "Your offer from Aperture Science",
                    "[image: Aperture Science] Hi Sam, Thank you again for interviewing with us. The whole team really enjoyed meeting you, and we're thrilled to extend an offer for the Test Engineer Intern role.",
                    3,
                )
            ],
            OFF,
            "offer",
            "Aperture Science",
            "Test Engineer Intern",
        )
    )
    return cs


def _lever_ashby() -> list[Case]:
    cs: list[Case] = []
    cs.append(
        app(
            "lv-conf-1",
            "lever",
            [
                m(
                    "Tyrell Corp",
                    LEVER,
                    "Thanks for applying to Tyrell Corp!",
                    "Hi Sam, Thanks for your interest in Tyrell Corp! We're delighted that you'd like to join our team as a Firmware Intern. We'll review your application and get back to you soon.",
                    15,
                )
            ],
            CONF,
            APPLIED,
            "Tyrell Corp",
            "Firmware Intern",
        )
    )
    cs.append(
        app(
            "lv-conf-2",
            "lever",
            [
                m(
                    "Massive Dynamic",
                    LEVER,
                    "Massive Dynamic - Application Received",
                    "Hi Sam, We received your application for Research Engineer Intern. Our recruiting team is reviewing it now. Thanks, Massive Dynamic Recruiting",
                    14,
                )
            ],
            CONF,
            APPLIED,
            "Massive Dynamic",
            "Research Engineer Intern",
        )
    )
    cs.append(
        app(
            "lv-rej-1",
            "lever",
            [
                m(
                    "Tyrell Corp",
                    LEVER,
                    "Your application to Tyrell Corp",
                    "Hi Sam, Thank you for your interest in Tyrell Corp and for taking the time to speak with our team. We've decided not to move forward with your candidacy at this time.",
                    3,
                )
            ],
            REJ,
            REJECTED,
            "Tyrell Corp",
            None,
        )
    )
    cs.append(
        app(
            "lv-rej-2",
            "lever",
            [
                m(
                    "Wonka Industries",
                    LEVER,
                    "Update from Wonka Industries",
                    "Hi Sam, Thanks so much for your interest in Wonka Industries. We know you put a lot of time into the process. After a lot of thought, we have decided to pursue other candidates for the Process Engineering Intern role.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Wonka Industries",
            "Process Engineering Intern",
        )
    )
    cs.append(
        app(
            "lv-int-1",
            "lever",
            [
                m(
                    "Massive Dynamic",
                    LEVER,
                    "Invitation to interview with Massive Dynamic",
                    "Hi Sam, Thank you for applying to Massive Dynamic. We would like to invite you to an interview for the Research Engineer Intern position. Please select a time below.",
                    7,
                )
            ],
            INT,
            "interview",
            "Massive Dynamic",
            "Research Engineer Intern",
        )
    )
    cs.append(
        app(
            "ab-conf-1",
            "ashby",
            [
                m(
                    "Ashby",
                    ASHBY,
                    "Thanks for applying to Northwind",
                    "Hi Sam, Thank you for applying to Northwind! We're thrilled you're interested in the Software Engineering Intern role. Our team will review your application and reach out if it's a match.",
                    13,
                )
            ],
            CONF,
            APPLIED,
            "Northwind",
            "Software Engineering Intern",
        )
    )
    cs.append(
        app(
            "ab-conf-2",
            "ashby",
            [
                m(
                    "Contoso via Ashby",
                    ASHBY,
                    "Application received: Frontend Intern at Contoso",
                    "Hi Sam, This is a confirmation that we received your application for the Frontend Intern position at Contoso. Please do not reply to this email.",
                    12,
                )
            ],
            CONF,
            APPLIED,
            "Contoso",
            "Frontend Intern",
        )
    )
    cs.append(
        app(
            "ab-rej-1",
            "ashby",
            [
                m(
                    "Ashby",
                    ASHBY,
                    "Your application to Northwind",
                    "Hi Sam, Thank you for your interest in Northwind and for the time you spent with us. We have decided to move forward with other candidates for this position.",
                    3,
                )
            ],
            REJ,
            REJECTED,
            "Northwind",
            None,
        )
    )
    cs.append(
        app(
            "ab-int-1",
            "ashby",
            [
                m(
                    "Contoso Recruiting",
                    ASHBY,
                    "Next steps: Frontend Intern at Contoso",
                    "Hi Sam, Great news! The hiring team at Contoso would like to move forward with you. Book a 45 minute technical conversation using the link below.",
                    6,
                )
            ],
            INT,
            "interview",
            "Contoso",
            "Frontend Intern",
        )
    )
    return cs


def _workday_icims_etc() -> list[Case]:
    cs: list[Case] = []
    cs.append(
        app(
            "wd-conf-1",
            "workday",
            [
                m(
                    "Fabrikam",
                    "fabrikam@myworkday.com",
                    "Thank you for applying to Fabrikam",
                    "Hello, Thank you for your interest in the Software Engineer Intern position (R-10442) at Fabrikam. We have received your application. Please do not reply to this email. This is an automated message.",
                    18,
                )
            ],
            CONF,
            APPLIED,
            "Fabrikam",
            SWE,
        )
    )
    cs.append(
        app(
            "wd-conf-2",
            "workday",
            [
                m(
                    "Adventure Works Careers",
                    "adventureworks@myworkday.com",
                    "Your Adventure Works application has been received",
                    "Hello Sam, Thank you for submitting your application to Adventure Works. Your application for Hardware Engineering Intern (Req 2231) is now under review. You can check your status at any time by signing in.",
                    17,
                )
            ],
            CONF,
            APPLIED,
            "Adventure Works",
            "Hardware Engineering Intern",
        )
    )
    cs.append(
        app(
            "wd-conf-3",
            "workday",
            [
                m(
                    "Litware",
                    "litware@wd5.myworkdayjobs.com",
                    "Litware Application Confirmation",
                    "Hello, Thank you for applying. Your application has been submitted successfully. If you wish to review it or make changes, log in to the Litware candidate home. Job: Analytics Intern",
                    16,
                )
            ],
            CONF,
            APPLIED,
            "Litware",
            "Analytics Intern",
        )
    )
    cs.append(
        app(
            "wd-rej-1",
            "workday",
            [
                m(
                    "Fabrikam",
                    "fabrikam@myworkday.com",
                    "Fabrikam Application Update",
                    "Hello, Thank you for your interest in the Software Engineer Intern position at Fabrikam. After careful review, we have decided to pursue other candidates for this role. We wish you the best.",
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Fabrikam",
            SWE,
        )
    )
    cs.append(
        app(
            "wd-rej-2",
            "workday",
            [
                m(
                    "Adventure Works Careers",
                    "adventureworks@myworkday.com",
                    "Update on your application",
                    "Hello Sam, Thank you for your interest in Adventure Works and for the time you have invested in our process. This email is to let you know that your application was not successful this time.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Adventure Works",
            None,
        )
    )
    cs.append(
        app(
            "wd-int-1",
            "workday",
            [
                m(
                    "Litware",
                    "litware@wd5.myworkdayjobs.com",
                    "Litware - Interview Request",
                    "Hello, Thank you for applying to Litware. We would like to schedule an interview for the Analytics Intern position. Please sign in to your candidate home to choose a time slot.",
                    8,
                )
            ],
            INT,
            "interview",
            "Litware",
            "Analytics Intern",
        )
    )
    cs.append(
        app(
            "ic-conf-1",
            "icims",
            [
                m(
                    "Proseware Careers",
                    "donotreply@icims.com",
                    "Thank you for applying to Proseware",
                    "Dear Sam, Thank you for your interest in a career at Proseware. We have received your application for the Cloud Engineer Intern opening and will review your qualifications.",
                    15,
                )
            ],
            CONF,
            APPLIED,
            "Proseware",
            "Cloud Engineer Intern",
        )
    )
    cs.append(
        app(
            "ic-rej-1",
            "icims",
            [
                m(
                    "Proseware Careers",
                    "donotreply@icims.com",
                    "Proseware Application Status",
                    "Dear Sam, Thank you for your interest in Proseware. We appreciate the time you took to apply. We regret to inform you that we have filled the position.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Proseware",
            None,
        )
    )
    cs.append(
        app(
            "sr-conf-1",
            "smartrecruiters",
            [
                m(
                    "Tailspin Toys",
                    "no-reply@smartrecruiters.com",
                    "Your application to Tailspin Toys",
                    "Hi Sam, Thank you for applying to Tailspin Toys for the Game Developer Intern job. We have received your application and our recruiters are reviewing it.",
                    14,
                )
            ],
            CONF,
            APPLIED,
            "Tailspin Toys",
            "Game Developer Intern",
        )
    )
    cs.append(
        app(
            "sr-int-1",
            "smartrecruiters",
            [
                m(
                    "Tailspin Toys",
                    "no-reply@smartrecruiters.com",
                    "Interview with Tailspin Toys",
                    "Hi Sam, We enjoyed reviewing your profile. We would like to invite you to an interview for the Game Developer Intern job. Please confirm your availability using the link below.",
                    6,
                )
            ],
            INT,
            "interview",
            "Tailspin Toys",
            "Game Developer Intern",
        )
    )
    cs.append(
        app(
            "wk-conf-1",
            "workable",
            [
                m(
                    "Lucerne Publishing Careers",
                    "no-reply@workable.com",
                    "Thanks for applying to Lucerne Publishing",
                    "Hi Sam, Thanks for applying for the Data Engineer Intern position at Lucerne Publishing. We've received your application and will get back to you soon. - The Lucerne Publishing hiring team",
                    13,
                )
            ],
            CONF,
            APPLIED,
            "Lucerne Publishing",
            "Data Engineer Intern",
        )
    )
    cs.append(
        app(
            "wk-rej-1",
            "workable",
            [
                m(
                    "Lucerne Publishing Careers",
                    "no-reply@workable.com",
                    "Your application for Data Engineer Intern",
                    "Hi Sam, Thank you for your interest in Lucerne Publishing. We regret to inform you that your application for Data Engineer Intern has been unsuccessful on this occasion.",
                    3,
                )
            ],
            REJ,
            REJECTED,
            "Lucerne Publishing",
            "Data Engineer Intern",
        )
    )
    cs.append(
        app(
            "jv-conf-1",
            "jobvite",
            [
                m(
                    "Blue Yonder Air",
                    "no-reply@jobvite.com",
                    "Blue Yonder Air - Thank you for your interest",
                    "Hi Sam, Thank you for applying for the Avionics Software Intern position. We have received your resume and will contact you if your qualifications match.",
                    12,
                )
            ],
            CONF,
            APPLIED,
            "Blue Yonder Air",
            "Avionics Software Intern",
        )
    )
    cs.append(
        app(
            "tl-rej-1",
            "taleo",
            [
                m(
                    "Gringotts Careers",
                    "donotreply@taleo.net",
                    "Gringotts - Application Status Update",
                    "Dear Sam, Thank you for your interest in the Risk Analyst Intern position. After careful consideration, we have selected another candidate whose experience more closely matches our needs.",
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Gringotts",
            "Risk Analyst Intern",
        )
    )
    return cs


def _boards() -> list[Case]:
    cs: list[Case] = []
    li = "jobs-noreply@linkedin.com"
    cs.append(
        app(
            "li-apply-1",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Sam, your application was sent to Acme",
                    "Your application was sent to Acme. Software Engineer Intern. Acme · Seattle, WA (Hybrid). Applied on Nov 1. View your application. Next steps: Acme will review your application.",
                    22,
                )
            ],
            CONF,
            APPLIED,
            "Acme",
            SWE,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "li-apply-2",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Your application to Data Analyst Intern at Northwind",
                    "Your application was sent to Northwind. Data Analyst Intern. Northwind · Remote. Applied on Nov 3. Keep your profile up to date so recruiters can find you.",
                    21,
                )
            ],
            CONF,
            APPLIED,
            "Northwind",
            "Data Analyst Intern",
        )
    )
    cs.append(
        app(
            "li-apply-3",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Sam, your application was sent to Globex",
                    "Your application was sent to Globex Software Engineer Intern - Summer 2027 Globex Chicago, IL Applied on Nov 4 Easy Apply",
                    20,
                )
            ],
            CONF,
            APPLIED,
            "Globex",
            "Software Engineer Intern",
        )
    )
    cs.append(
        noise(
            "li-viewed-1",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Your application was viewed by Contoso",
                    "Good news, Sam. Your application for Frontend Intern at Contoso was viewed by the hiring team. See who else viewed your profile this week. Unsubscribe",
                    10,
                )
            ],
        )
    )
    cs.append(
        app(
            "li-rej-1",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Your update from Northwind",
                    "Thank you for your interest in the Data Analyst Intern role at Northwind. Unfortunately, we will not be moving forward with your application at this time. Learn more about similar jobs on LinkedIn.",
                    2,
                )
            ],
            REJ,
            REJECTED,
            "Northwind",
            "Data Analyst Intern",
        )
    )
    cs.append(
        app(
            "in-apply-1",
            "indeed",
            [
                m(
                    "Indeed Apply",
                    "indeedapply@indeed.com",
                    "Indeed Application: Support Engineer Intern",
                    "Application submitted. Support Engineer Intern - Soylent - Austin, TX. Your application has been sent to the employer. Good luck! Review your application",
                    19,
                )
            ],
            CONF,
            APPLIED,
            "Soylent",
            "Support Engineer Intern",
        )
    )
    cs.append(
        app(
            "in-apply-2",
            "indeed",
            [
                m(
                    "Indeed Apply",
                    "indeedapply@indeed.com",
                    "Indeed Application: QA Intern",
                    "Application submitted. QA Intern - Hooli - Remote. We will let you know if the employer contacts you. Manage your Indeed job alerts",
                    18,
                )
            ],
            CONF,
            APPLIED,
            "Hooli",
            "QA Intern",
        )
    )
    cs.append(
        app(
            "hs-apply-1",
            "handshake",
            [
                m(
                    "Handshake",
                    "no-reply@joinhandshake.com",
                    "You applied to Software Engineer Intern at Initech",
                    "Hi Sam, you've successfully applied to Software Engineer Intern at Initech. Employers typically respond within 2 weeks. Stay on top of your applications in Handshake.",
                    17,
                )
            ],
            CONF,
            APPLIED,
            "Initech",
            SWE,
        )
    )
    cs.append(
        app(
            "hs-msg-1",
            "handshake",
            [
                m(
                    "Handshake",
                    "no-reply@joinhandshake.com",
                    "Wayne Systems sent you a message",
                    "Wayne Systems sent you a message about your application: Hi Sam, we'd like to invite you to an interview for the Security Intern role. Reply on Handshake to pick a time.",
                    8,
                )
            ],
            INT,
            "interview",
            "Wayne Systems",
            "Security Intern",
        )
    )
    return cs


def _direct_and_assessments() -> list[Case]:
    cs: list[Case] = []
    cs.append(
        app(
            "dir-conf-1",
            "direct",
            [
                m(
                    "Acme Careers",
                    "careers@acme-corp.example",
                    "We've received your application",
                    "Hi Sam, thank you for applying to Acme! Your application for Software Engineer Intern has been received. We'll be in touch. Acme Careers | 100 Main St",
                    20,
                )
            ],
            CONF,
            APPLIED,
            "Acme",
            SWE,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "dir-conf-2",
            "direct",
            [
                m(
                    "Jobs at Stark",
                    "jobs@stark-dynamics.example",
                    "Application confirmation",
                    "Dear Applicant, This is an automatic confirmation that your application was submitted. We receive many applications and will contact shortlisted candidates only. Do not reply.",
                    16,
                )
            ],
            CONF,
            APPLIED,
            "Stark Dynamics",
            None,
        )
    )
    cs.append(
        app(
            "dir-conf-3",
            "direct",
            [
                m(
                    "Recruiting",
                    "recruiting@umbrella-labs.example",
                    "Re: Machine Learning Intern",
                    "Hi Sam, thanks for sending your resume. We have your application and will review it this week.",
                    15,
                )
            ],
            CONF,
            APPLIED,
            "Umbrella Labs",
            "Machine Learning Intern",
        )
    )
    cs.append(
        app(
            "dir-rej-1",
            "direct",
            [
                m(
                    "Hooli Recruiting Team",
                    "recruiting@hooli.example",
                    "Your Hooli application",
                    "Hi Sam, thank you for your interest in Hooli. We wanted to let you know that we have decided not to proceed with your application for the Backend Intern role. We wish you every success.",
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Hooli",
            "Backend Intern",
        )
    )
    cs.append(
        app(
            "dir-rej-2",
            "direct",
            [
                m(
                    "Priya Raman",
                    "priya.raman@initech.example",
                    "Re: Platform Engineering Intern",
                    "Hi Sam, Thanks for chatting with me last week. I wanted to follow up personally: we ended up going with another candidate for the Platform Engineering Intern internship. Keep in touch!",
                    3,
                )
            ],
            REJ,
            REJECTED,
            "Initech",
            "Platform Engineering Intern",
        )
    )
    cs.append(
        app(
            "dir-int-1",
            "direct",
            [
                m(
                    "Jordan Lee",
                    "jordan.lee@acme-corp.example",
                    "Interview availability",
                    "Hi Sam, This is Jordan from Acme. Could you share your availability for an interview next week? The interview is 45 minutes with two engineers from the team.",
                    12,
                )
            ],
            INT,
            "interview",
            "Acme",
            None,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "dir-int-2",
            "direct",
            [
                m(
                    "Talent Team",
                    "talent@acme-corp.example",
                    "Acme | Interview Confirmation",
                    "Hi Sam, your interview is confirmed for Tue, Dec 2 at 2:00 PM PST. You will meet with Dana and Chris. Join via the Zoom link below. Please do not reply.",
                    7,
                )
            ],
            INT,
            "interview",
            "Acme",
            None,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "dir-int-3",
            "direct",
            [
                m(
                    "Dana Whitfield",
                    "dana.whitfield@globex.example",
                    "Next steps with Globex",
                    "Hi Sam, thanks for the great conversation. We'd love to move you to the next round, a final panel with the team. When are you free this week?",
                    6,
                )
            ],
            INT,
            "interview",
            "Globex",
            None,
        )
    )
    cs.append(
        app(
            "dir-off-1",
            "direct",
            [
                m(
                    "Aisha Khan",
                    "aisha.khan@hooli.example",
                    "Offer - Hooli Backend Intern",
                    "Hi Sam, I'm delighted to share that we would like to offer you the Backend Intern position at Hooli for Summer 2027. Details about compensation and start date are below.",
                    2,
                )
            ],
            OFF,
            "offer",
            "Hooli",
            "Backend Intern",
        )
    )
    cs.append(
        app(
            "oa-hr-1",
            "hackerrank",
            [
                m(
                    "HackerRank",
                    "no-reply@hackerrank.com",
                    "Invitation to complete your HackerRank assessment",
                    "Hi Sam, Acme has invited you to take an online assessment: Software Engineer Intern Coding Test. You have 7 days to complete it. Duration 90 minutes. Start now",
                    15,
                )
            ],
            OA,
            "online_assessment",
            "Acme",
            SWE,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "oa-hr-2",
            "hackerrank",
            [
                m(
                    "Globex Recruiting via HackerRank",
                    "no-reply@hackerrankforwork.com",
                    "Globex invites you to a coding challenge",
                    "Hi Sam, You have been invited by Globex to take a coding challenge for the Data Science Intern role. Please complete it within 5 days. Good luck!",
                    14,
                )
            ],
            OA,
            "online_assessment",
            "Globex",
            "Data Science Intern",
        )
    )
    cs.append(
        app(
            "oa-cs-1",
            "codesignal",
            [
                m(
                    "CodeSignal",
                    "no-reply@codesignal.com",
                    "Fabrikam wants you to take a CodeSignal assessment",
                    "[image: CodeSignal] Hi Sam, Fabrikam has invited you to complete the General Coding Assessment as part of your application. This message was sent to sam.student@mail.example",
                    13,
                )
            ],
            OA,
            "online_assessment",
            "Fabrikam",
            None,
        )
    )
    cs.append(
        app(
            "oa-gh-1",
            "greenhouse",
            [
                m(
                    "Initech",
                    GH,
                    "Next steps: complete your take-home",
                    "Hi Sam, Thanks for applying to Initech. The next step is a short take-home exercise for the Platform Engineering Intern role. You'll have 48 hours once you start.",
                    12,
                )
            ],
            OA,
            "online_assessment",
            "Initech",
            "Platform Engineering Intern",
        )
    )
    cs.append(
        app(
            "oa-direct-1",
            "direct",
            [
                m(
                    "Hiring Team",
                    "hiring@wayne-systems.example",
                    "Your Wayne Systems assessment",
                    "Hi Sam, as the next step in your application for Security Intern, please complete the assessment linked below. It should take about 60 minutes and must be finished within 72 hours.",
                    11,
                )
            ],
            OA,
            "online_assessment",
            "Wayne Systems",
            "Security Intern",
        )
    )
    cs.append(
        app(
            "oa-hirevue-1",
            "hirevue",
            [
                m(
                    "HireVue",
                    "no-reply@hirevue.com",
                    "Soylent: Complete your HireVue interview",
                    "Hi Sam, Soylent has invited you to complete a one-way video interview for the Product Design Intern position. You can record at any time within 7 days.",
                    10,
                )
            ],
            INT,
            "interview",
            "Soylent",
            "Product Design Intern",
        )
    )
    cs.append(
        app(
            "cal-1",
            "calendar",
            [
                m(
                    "Jordan Lee (via Google Calendar)",
                    "calendar-notification@google.com",
                    "Invitation: Acme Interview @ Tue Dec 2, 2026 2pm - 3pm (PST) (sam.student@mail.example)",
                    "Acme Interview When Tue Dec 2, 2026 2pm - 3pm Pacific Time Joining info Join with Google Meet meet.google.com/abc-defg-hij Calendar sam.student@mail.example Who Jordan Lee organizer",
                    8,
                )
            ],
            INT,
            "interview",
            "Acme",
            None,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "cal-2",
            "calendar",
            [
                m(
                    "Chris Park (via Zoom)",
                    "no-reply@zoom.us",
                    "Invitation: Globex Final Interview",
                    "Chris Park is inviting you to a scheduled Zoom meeting. Topic: Globex Final Interview Time: Dec 3, 2026 10:00 AM Pacific Time Join Zoom Meeting",
                    5,
                )
            ],
            INT,
            "interview",
            "Globex",
            None,
        )
    )
    cs.append(
        app(
            "cal-3",
            "calendar",
            [
                m(
                    "Calendly",
                    "notifications@calendly.com",
                    "Confirmed: 30 Minute Chat with Dana Whitfield - Globex",
                    "Hi Sam, Your 30 Minute Chat with Dana Whitfield at Globex is scheduled for Tue Dec 2, 2026 at 10:00am. Add to calendar. Need to make changes? Cancel or reschedule",
                    5,
                )
            ],
            INT,
            "interview",
            "Globex",
            None,
        )
    )
    return cs


def _threads() -> list[Case]:
    """Multi-message threads and one application spread over separate threads."""
    gh = "Acme Talent Acquisition"
    cs: list[Case] = []
    cs.append(
        app(
            "mt-conf-oa-rej",
            "multi",
            [
                m(
                    "Northwind Careers",
                    ASHBY,
                    "Your Northwind application",
                    "Hi Sam, Thank you for applying to Northwind for the Software Engineering Intern role. We received your application.",
                    26,
                ),
                m(
                    "Northwind Careers",
                    ASHBY,
                    "Your Northwind application",
                    "Hi Sam, as a next step please complete this online assessment within 5 days.",
                    20,
                ),
                m(
                    "Northwind Careers",
                    ASHBY,
                    "Your Northwind application",
                    "Hi Sam, Thank you for completing the assessment. Unfortunately we will not be moving forward with your application.",
                    9,
                ),
            ],
            REJ,
            REJECTED,
            "Northwind",
            "Software Engineering Intern",
        )
    )
    cs.append(
        app(
            "mt-user-reply-last",
            "multi",
            [
                m(
                    "Dana Whitfield",
                    "dana.whitfield@globex.example",
                    "Next steps with Globex",
                    "Hi Sam, we would like to schedule an interview with you. Are you available Tuesday or Wednesday?",
                    9,
                ),
                m(
                    "Sam Student",
                    ME,
                    "Re: Next steps with Globex",
                    "Hi Dana, Wednesday works great for me. I'm free after 1pm Pacific. Thanks!",
                    8,
                    user=True,
                ),
            ],
            INT,
            "interview",
            "Globex",
            None,
        )
    )
    cs.append(
        app(
            "mt-schedule-backforth",
            "multi",
            [
                m(
                    "Jordan Lee",
                    "jordan.lee@acme-corp.example",
                    "Re: Interview availability",
                    "Hi Sam, This is Jordan from Acme. Could you share your availability for an interview next week?",
                    14,
                ),
                m(
                    "Sam Student",
                    ME,
                    "Re: Interview availability",
                    "Hi Jordan, I'm free Tue and Thu afternoon.",
                    13,
                    user=True,
                ),
                m(
                    "Jordan Lee",
                    "jordan.lee@acme-corp.example",
                    "Re: Interview availability",
                    "Great, thanks Sam. Sounds good, I'll send a calendar invite shortly. Talk soon!",
                    12,
                ),
                m(
                    "Sam Student",
                    ME,
                    "Re: Interview availability",
                    "Perfect, see you then.",
                    12,
                    user=True,
                ),
            ],
            INT,
            "interview",
            "Acme",
            None,
        )
    )
    cs.append(
        app(
            "mt-sched-ack-last",
            "multi",
            [
                m(
                    "Priya Raman",
                    "priya.raman@initech.example",
                    "Initech interview",
                    "Hi Sam, we'd like to invite you to an interview for the Platform Engineering Intern role.",
                    10,
                ),
                m(
                    "Sam Student",
                    ME,
                    "Re: Initech interview",
                    "Thursday at 3pm works for me, thank you!",
                    9,
                    user=True,
                ),
                m(
                    "Priya Raman",
                    "priya.raman@initech.example",
                    "Re: Initech interview",
                    "Perfect, you're all set. Looking forward to it!",
                    9,
                ),
            ],
            INT,
            "interview",
            "Initech",
            "Platform Engineering Intern",
        )
    )
    cs.append(
        app(
            "mt-conf-then-int",
            "multi",
            [
                m(
                    "Hooli",
                    GH,
                    "Thank you for applying to Hooli",
                    "Hi Sam, Thank you for applying to the Backend Intern position at Hooli. We received your application.",
                    18,
                ),
                m(
                    "Hooli",
                    GH,
                    "Next steps with Hooli",
                    "Hi Sam, Thank you for your interest in Hooli. We would like to schedule an interview with you for the Backend Intern position.",
                    11,
                ),
            ],
            INT,
            "interview",
            "Hooli",
            "Backend Intern",
        )
    )
    cs.append(
        app(
            "mt-int-then-wait",
            "multi",
            [
                m(
                    "Soylent",
                    GH,
                    "Interview invitation - Soylent",
                    "Hi Sam, we would like to schedule an interview for the Product Design Intern role. Use the link to pick a time.",
                    12,
                ),
                m(
                    "Soylent",
                    GH,
                    "Reminder: your Soylent interview",
                    "Hi Sam, this is a friendly reminder about your upcoming interview tomorrow at 11:00 AM. Please do not reply to this email.",
                    7,
                ),
            ],
            INT,
            "interview",
            "Soylent",
            "Product Design Intern",
        )
    )
    cs.append(
        app(
            "mt-draft-last",
            "multi",
            [
                m(
                    "Aisha Khan",
                    "aisha.khan@hooli.example",
                    "Offer - Hooli Backend Intern",
                    "Hi Sam, we would like to offer you the Backend Intern position at Hooli. Details are below. Offer letter attached.",
                    6,
                ),
                m(
                    "Sam Student",
                    ME,
                    "Re: Offer - Hooli Backend Intern",
                    "Hi Aisha, thank you so much! I accept",
                    5,
                    user=True,
                    draft=True,
                ),
            ],
            OFF,
            "offer",
            "Hooli",
            "Backend Intern",
        )
    )
    # Same application on separate threads: confirmation, OA, interview invite each in its own thread.
    cs.append(
        app(
            "sp-fabrikam-conf",
            "split",
            [
                m(
                    "Fabrikam",
                    "fabrikam@myworkday.com",
                    "Thank you for applying to Fabrikam",
                    "Hello, Thank you for your interest in the Cloud Support Intern position at Fabrikam. We have received your application.",
                    23,
                )
            ],
            CONF,
            APPLIED,
            "Fabrikam",
            "Cloud Support Intern",
            group="g-fabrikam",
        )
    )
    cs.append(
        app(
            "sp-fabrikam-oa",
            "split",
            [
                m(
                    "CodeSignal",
                    "no-reply@codesignal.com",
                    "Fabrikam wants you to take a CodeSignal assessment",
                    "Hi Sam, Fabrikam has invited you to complete the General Coding Assessment for the Cloud Support Intern role. You have 7 days.",
                    18,
                )
            ],
            OA,
            "online_assessment",
            "Fabrikam",
            "Cloud Support Intern",
            group="g-fabrikam",
        )
    )
    cs.append(
        app(
            "sp-fabrikam-int",
            "split",
            [
                m(
                    "Fabrikam",
                    "fabrikam@myworkday.com",
                    "Fabrikam - Interview Request",
                    "Hello, We would like to schedule an interview for the Cloud Support Intern position. Please sign in to choose a time.",
                    9,
                )
            ],
            INT,
            "interview",
            "Fabrikam",
            "Cloud Support Intern",
            group="g-fabrikam",
        )
    )
    cs.append(
        app(
            "sp-acme-rej",
            "split",
            [
                m(
                    gh,
                    GH,
                    "Update on your Acme application",
                    "Hi Sam, Thank you for interviewing for the Software Engineer Intern role at Acme. After careful consideration, we have decided to move forward with other candidates.",
                    3,
                )
            ],
            REJ,
            REJECTED,
            "Acme",
            SWE,
            group="g-acme-swe",
        )
    )
    cs.append(
        app(
            "sp-li-contoso",
            "split",
            [
                m(
                    "LinkedIn",
                    "jobs-noreply@linkedin.com",
                    "Sam, your application was sent to Contoso",
                    "Your application was sent to Contoso. Frontend Intern. Contoso · Remote. Applied on Nov 2. Easy Apply",
                    22,
                )
            ],
            CONF,
            APPLIED,
            "Contoso",
            "Frontend Intern",
            group="g-contoso",
        )
    )
    cs.append(
        app(
            "sp-contoso-ats",
            "split",
            [
                m(
                    "Contoso",
                    ASHBY,
                    "Application received: Frontend Intern at Contoso",
                    "Hi Sam, This is a confirmation that we received your application for the Frontend Intern position at Contoso.",
                    22,
                )
            ],
            CONF,
            APPLIED,
            "Contoso",
            "Frontend Intern",
            group="g-contoso",
        )
    )
    return cs


def _recruiters() -> list[Case]:
    return [
        rec(
            "rc-1",
            "recruiter",
            [
                m(
                    "Taylor Brooks",
                    "taylor.brooks@wonka.example",
                    "Opportunity at Wonka Industries",
                    "Hi Sam, I came across your profile on LinkedIn and was impressed by your projects. I'm reaching out about a Software Engineering Intern role at Wonka Industries. Would you be open to a quick chat?",
                    12,
                )
            ],
        ),
        rec(
            "rc-2",
            "recruiter",
            [
                m(
                    "Morgan Diaz",
                    "morgan@talentbridge.example",
                    "Internship roles you may like",
                    "Hi Sam, My name is Morgan and I'm a technical recruiter at TalentBridge. We're hiring interns for several clients. Are you interested in learning more? Please send your resume.",
                    11,
                )
            ],
        ),
        rec(
            "rc-3",
            "recruiter",
            [
                m(
                    "LinkedIn",
                    "inmail-hit-reply@linkedin.com",
                    "Riley Chen messaged you about a role at Gringotts",
                    "Riley Chen from Gringotts: Hi Sam, we're building out our summer intern class and your background in data caught our eye. Would you be interested in a Risk Analyst Intern position?",
                    10,
                )
            ],
        ),
        rec(
            "rc-4",
            "recruiter",
            [
                m(
                    "Casey Nguyen",
                    "casey.nguyen@umbrella-labs.example",
                    "Quick intro from Umbrella Labs",
                    "Hi Sam, Casey here from Umbrella Labs. I saw your GitHub and wanted to connect. We have openings for ML interns this summer; happy to share details if you're interested.",
                    9,
                )
            ],
        ),
        rec(
            "rc-5",
            "recruiter",
            [
                m(
                    "University Career Center",
                    "careers@university.example",
                    "Employer spotlight: Tyrell Corp is hiring interns",
                    "Tyrell Corp is hiring Firmware Interns for Summer 2027. Apply through Handshake by Dec 5. Info session Nov 30. View this email in your browser",
                    8,
                )
            ],
        ),
        rec(
            "rc-6",
            "recruiter",
            [
                m(
                    "Jamie Ortiz",
                    "jamie.ortiz@cyberdyne.example",
                    "Re: your resume",
                    "Hi Sam, thanks for sending your resume to the career fair booth. We'd love to keep in touch about internships at Cyberdyne. Do you have time for a quick call this week?",
                    7,
                )
            ],
        ),
    ]


def _noise() -> list[Case]:
    n: list[Case] = []
    n += [
        noise(
            "n-alert-1",
            "noise.job_alert",
            [
                m(
                    "LinkedIn Job Alerts",
                    "jobalerts-noreply@linkedin.com",
                    '"software engineer intern": Acme and 24 more new jobs in United States',
                    "Your job alert for software engineer intern in United States. 25 new jobs match your preferences. Acme - Software Engineer Intern - Seattle, WA. See all jobs",
                    3,
                )
            ],
        ),
        noise(
            "n-alert-2",
            "noise.job_alert",
            [
                m(
                    "Indeed",
                    "alert@indeed.com",
                    "New jobs for you: Data Intern in Austin",
                    "Data Intern - Soylent - Austin, TX. Analytics Intern - Hooli - Remote. 12 new jobs for you. Unsubscribe from this job alert",
                    4,
                )
            ],
        ),
        noise(
            "n-alert-3",
            "noise.job_alert",
            [
                m(
                    "Glassdoor Jobs",
                    "noreply@glassdoor.com",
                    "Jobs you may be interested in this week",
                    "Software Engineer Intern at Initech, Backend Intern at Hooli and 8 more. Manage your job alerts. This message was sent to sam.student@mail.example",
                    5,
                )
            ],
        ),
        noise(
            "n-alert-4",
            "noise.job_alert",
            [
                m(
                    "Handshake",
                    "no-reply@joinhandshake.com",
                    "5 new jobs matching your preferences",
                    "Hi Sam, employers on Handshake posted new internships that match your interests: Frontend Intern, Cloud Engineer Intern. View all",
                    6,
                )
            ],
        ),
        noise(
            "n-li-1",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    "notifications-noreply@linkedin.com",
                    "Sam, you appeared in 9 searches this week",
                    "See who's looking at your profile. Your profile appeared in 9 searches. Upgrade to Premium. You are receiving LinkedIn notification emails. Unsubscribe",
                    4,
                )
            ],
        ),
        noise(
            "n-li-2",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    "invitations@linkedin.com",
                    "Priya Raman wants to connect",
                    "Priya Raman, Technical Recruiter at Initech, would like to connect with you on LinkedIn. Accept. View profile",
                    5,
                )
            ],
        ),
        noise(
            "n-li-3",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    "messages-noreply@linkedin.com",
                    "Dana Whitfield just messaged you",
                    "Dana Whitfield: Thanks for connecting, Sam! Reply to this message on LinkedIn. You are receiving message notification emails. Unsubscribe",
                    6,
                )
            ],
        ),
        noise(
            "n-news-1",
            "noise.newsletter",
            [
                m(
                    "Morning Brew",
                    "crew@morningbrew.example",
                    "Markets rally on rate-cut hopes",
                    "View this email in your browser. Good morning. Stocks climbed, tech led gains, and a new AI chip startup raised $400M. Here's what you need to know today.",
                    2,
                )
            ],
        ),
        noise(
            "n-news-2",
            "noise.newsletter",
            [
                m(
                    "TLDR",
                    "dan@tldr.example",
                    "TLDR 2026-11-17: Rust in the kernel, new Postgres release",
                    "Big Tech and Startups: Open source maintainers push back. Programming, Design and Data Science: Postgres 18.2 is out. Sponsored: hire engineers faster. Unsubscribe",
                    1,
                )
            ],
        ),
        noise(
            "n-news-3",
            "noise.newsletter",
            [
                m(
                    "Career Weekly",
                    "news@careers-weekly.example",
                    "How to write a resume that gets interviews",
                    "This week: five resume mistakes, how to prepare for a technical interview, and 10 companies hiring interns right now. Read more on our blog. Unsubscribe",
                    7,
                )
            ],
        ),
        noise(
            "n-news-4",
            "noise.newsletter",
            [
                m(
                    "Hacker Digest",
                    "digest@hackerdigest.example",
                    "Weekly digest: your career in tech",
                    "Top stories: career advice from senior engineers, hiring trends for 2027 and a new coding challenge platform. Read online. Manage preferences",
                    9,
                )
            ],
        ),
        noise(
            "n-rcpt-1",
            "noise.receipt",
            [
                m(
                    "Uber Receipts",
                    "uber.us@uber.example",
                    "Your Tuesday evening trip with Uber",
                    "Thanks for riding, Sam. Total $14.20. Pickup 6:42 PM 123 Campus Dr. Drop-off 7:01 PM. Rate your driver. Download your receipt",
                    3,
                )
            ],
        ),
        noise(
            "n-rcpt-2",
            "noise.receipt",
            [
                m(
                    "Amazon.com",
                    "auto-confirm@amazon.example",
                    "Your Amazon.com order #112-3456789-0123456",
                    "Hello Sam, thank you for shopping with us. We'll send a confirmation when your item ships. Arriving Thursday. Order total $32.99",
                    4,
                )
            ],
        ),
        noise(
            "n-rcpt-3",
            "noise.receipt",
            [
                m(
                    "Spotify",
                    "no-reply@spotify.example",
                    "Your receipt from Spotify",
                    "Thanks for being a Premium Student subscriber. Your payment of $5.99 was received. Next payment on Dec 14. Manage your subscription",
                    6,
                )
            ],
        ),
        noise(
            "n-school-1",
            "noise.school",
            [
                m(
                    "Registrar",
                    "registrar@university.example",
                    "Spring 2027 course registration opens Nov 30",
                    "Dear students, registration for Spring 2027 opens on November 30 at 8:00 AM. Check your enrollment appointment in the student portal. Holds must be cleared",
                    5,
                )
            ],
        ),
        noise(
            "n-school-2",
            "noise.school",
            [
                m(
                    "CS Department",
                    "cs-announce@university.example",
                    "Reminder: CS 301 midterm review session",
                    "Hi all, the review session for the CS 301 midterm will be held Thursday 6pm in Room 204. Bring questions. Office hours are cancelled this week",
                    3,
                )
            ],
        ),
        noise(
            "n-school-3",
            "noise.school",
            [
                m(
                    "Career Services",
                    "careers@university.example",
                    "Career Fair: Spring Tech Career Fair on Feb 10",
                    "Registration is now open for the Spring Tech Career Fair. Over 80 employers will attend. Sign up in Handshake. Resume review drop-ins every Wednesday",
                    8,
                )
            ],
        ),
        noise(
            "n-school-4",
            "noise.school",
            [
                m(
                    "Prof. Alvarez",
                    "alvarez@university.example",
                    "Recommendation letter",
                    "Hi Sam, happy to write you a recommendation for your internship applications. Please send me your resume and the deadlines. Best, Prof. Alvarez",
                    10,
                )
            ],
        ),
        noise(
            "n-misc-1",
            "noise.misc",
            [
                m(
                    "GitHub",
                    "noreply@github.example",
                    "[GitHub] A new public key was added to your account",
                    "Hey sam-student! A new public key was added to your account. If you did not add this key, please review your security settings. Thanks, The GitHub Team",
                    5,
                )
            ],
        ),
        noise(
            "n-misc-2",
            "noise.misc",
            [
                m(
                    "Mom",
                    "mom@family.example",
                    "Thanksgiving plans",
                    "Hi sweetie, are you coming home on Wednesday or Thursday? Dad can pick you up from the station. Love, Mom",
                    2,
                )
            ],
        ),
        noise(
            "n-misc-3",
            "noise.misc",
            [
                m(
                    "Chase",
                    "no.reply.alerts@chase.example",
                    "Your statement is ready",
                    "Your November statement is now available. Sign in to view your balance and recent transactions. This is a service message. Please do not reply",
                    6,
                )
            ],
        ),
        noise(
            "n-misc-4",
            "noise.misc",
            [
                m(
                    "Coursera",
                    "no-reply@coursera.example",
                    "Finish what you started: Algorithms Specialization",
                    "Hi Sam, you're 62% through Algorithms, Part II. Pick up where you left off. Keep your streak going! Unsubscribe",
                    7,
                )
            ],
        ),
        noise(
            "n-misc-5",
            "noise.misc",
            [
                m(
                    "Airbnb",
                    "automated@airbnb.example",
                    "Reservation reminder for your upcoming stay",
                    "Hi Sam, your stay in Boston starts in 3 days. Check-in after 3:00 PM. Message your host with any questions. View reservation",
                    3,
                )
            ],
        ),
        noise(
            "n-misc-6",
            "noise.misc",
            [
                m(
                    "Strava",
                    "no-reply@strava.example",
                    "Sam, your weekly activity summary",
                    "You ran 14.2 km this week, up 12% from last week. See your new personal records. Follow friends to compare. Unsubscribe",
                    4,
                )
            ],
        ),
        noise(
            "n-trap-1",
            "noise.trap",
            [
                m(
                    "Roommate",
                    "alex.kim@mail2.example",
                    "Who's the role model for the group project?",
                    "Hey Sam, I'm thinking you should take the lead on the presentation. You applied your design skills last time. Position yourself near the front. Interview with the TA tomorrow?",
                    4,
                )
            ],
        ),
        noise(
            "n-trap-2",
            "noise.trap",
            [
                m(
                    "Handshake",
                    "no-reply@joinhandshake.com",
                    "Employers are viewing your profile",
                    "Hi Sam, 3 employers viewed your profile this week. Complete your profile to get more views. Upload your resume. Update your career interests",
                    6,
                )
            ],
        ),
        noise(
            "n-trap-3",
            "noise.trap",
            [
                m(
                    "Medium Daily Digest",
                    "noreply@medium.example",
                    "How I prepared for 30 internship interviews",
                    "Stories for Sam: How I prepared for 30 internship interviews, The truth about coding challenges, and Why I left my offer. Read more. Unsubscribe",
                    5,
                )
            ],
        ),
        noise(
            "n-trap-4",
            "noise.trap",
            [
                m(
                    "Sam Student",
                    ME,
                    "Internship application notes",
                    "Notes to self: follow up with Acme on Friday, ask about the Software Engineer Intern application status and prepare questions for the interview.",
                    6,
                    user=True,
                )
            ],
        ),
    ]
    return n


def _extra() -> list[Case]:
    ic = "donotreply@icims.com"
    return [
        app(
            "wd-off-1",
            "workday",
            [
                m(
                    "Litware",
                    "litware@wd5.myworkdayjobs.com",
                    "Litware Offer Letter",
                    "Hello Sam, Congratulations! We are pleased to extend you an offer of employment for the Analytics Intern position. Your offer letter is available in your candidate home.",
                    2,
                )
            ],
            OFF,
            "offer",
            "Litware",
            "Analytics Intern",
        ),
        app(
            "ab-off-1",
            "ashby",
            [
                m(
                    "Northwind",
                    ASHBY,
                    "Offer from Northwind",
                    "Hi Sam, We're thrilled to offer you the Software Engineering Intern position at Northwind! Please find your offer letter attached and let us know if you have any questions.",
                    1,
                )
            ],
            OFF,
            "offer",
            "Northwind",
            "Software Engineering Intern",
        ),
        app(
            "gh-rej-5",
            "greenhouse",
            [
                m(
                    "Tyrell Corp",
                    GH,
                    "Thank you for your interest in Tyrell Corp",
                    "Hi Sam, Thank you for your interest in the Firmware Intern role at Tyrell Corp. We have reviewed your qualifications and have chosen to proceed with applicants whose experience more closely aligns with our needs.",
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Tyrell Corp",
            "Firmware Intern",
        ),
        app(
            "gh-conf-6",
            "greenhouse",
            [
                m(
                    "Massive Dynamic",
                    GH,
                    "Thank you for applying",
                    "[image: Massive Dynamic logo] View this email in your browser Please do not reply to this email. This message was sent to sam.student@mail.example by Greenhouse on behalf of Massive Dynamic. ",
                    13,
                    tail="Hi Sam, thank you for applying to the Research Engineer Intern role. We received your application.",
                )
            ],
            CONF,
            APPLIED,
            "Massive Dynamic",
            "Research Engineer Intern",
        ),
        app(
            "lv-conf-3",
            "lever",
            [
                m(
                    "Lucerne Publishing",
                    LEVER,
                    "Thanks for your application",
                    "Hi Sam, Thanks for applying! We'll get back to you soon. Sent via Lever.",
                    12,
                )
            ],
            CONF,
            APPLIED,
            "Lucerne Publishing",
            None,
        ),
        app(
            "ic-int-1",
            "icims",
            [
                m(
                    "Proseware Careers",
                    ic,
                    "Proseware: Schedule your interview",
                    "Dear Sam, Congratulations! You have been selected to move forward in the hiring process for Cloud Engineer Intern. Please log in to schedule your phone screen.",
                    7,
                )
            ],
            INT,
            "interview",
            "Proseware",
            "Cloud Engineer Intern",
        ),
        app(
            "jv-rej-1",
            "jobvite",
            [
                m(
                    "Blue Yonder Air",
                    "no-reply@jobvite.com",
                    "Update on your application",
                    "Hi Sam, Thank you for your interest in Blue Yonder Air. We appreciate your time. At this point we are not able to offer you the Avionics Software Intern position.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Blue Yonder Air",
            "Avionics Software Intern",
        ),
        app(
            "dir-conf-4",
            "direct",
            [
                m(
                    "Careers at Gringotts",
                    "no-reply@gringotts.example",
                    "Application Submitted",
                    "Hi Sam, Your application has been submitted. Job title: Risk Analyst Intern. Location: Boston, MA. Reference: GR-2291. You can check your status in the candidate portal.",
                    17,
                )
            ],
            CONF,
            APPLIED,
            "Gringotts",
            "Risk Analyst Intern",
        ),
        app(
            "dir-rej-3",
            "direct",
            [
                m(
                    "Gringotts Recruiting",
                    "no-reply@gringotts.example",
                    "Your application for Risk Analyst Intern",
                    "Dear Sam, Thank you for applying. While your background is impressive, we have decided not to proceed further with your application. We encourage you to apply again in the future.",
                    2,
                )
            ],
            REJ,
            REJECTED,
            "Gringotts",
            "Risk Analyst Intern",
        ),
    ]


def build_corpus() -> list[Case]:
    cases = [
        *_greenhouse(),
        *_lever_ashby(),
        *_workday_icims_etc(),
        *_boards(),
        *_direct_and_assessments(),
        *_threads(),
        *_recruiters(),
        *_noise(),
        *_extra(),
    ]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases
