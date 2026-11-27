# ruff: noqa: E501
"""HOLDOUT pipeline corpus: synthetic threads with full plain-text bodies. FROZEN.

Written before any product change of the "real email -> card" work and never edited afterwards:
do not read its misses to decide what to add to rules or extraction (tune split only). Companies,
people and phrasings differ from the tune split. The student is "Sam". Everything is invented.
Gmail snippets are derived from the body the way Gmail previews do (first ~200 characters).
Expectations are what a user would want, not what the code does.
"""

from eval.pipeline_corpus.model import Case, Msg, gmail_snippet

ME = "sam.student@mail.example"
INT, OA, CONF, REJ, OFF = "interview", "online_assessment", "confirmation", "rejection", "offer"
APPLIED, REJECTED = "applied", "rejected"


def m(name: str, addr: str, subj: str, body: str, day: int, *, user: bool = False) -> Msg:
    return Msg(name, addr, subj, gmail_snippet(body), day, user, False, "", body)


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


FOOT_GH = (
    "\n\nThis email was sent by Greenhouse on behalf of the employer. Unsubscribe | Privacy Policy"
)
FOOT_NOREPLY = "\n\nThis is an automated message. Please do not reply to this email."


def _workday() -> list[Case]:
    return [
        app(
            "h-wd-conf-1",
            "workday",
            [
                m(
                    "Initrode Careers",
                    "initrode@myworkday.com",
                    "Thank you for applying",
                    "Hi Sam,\n\nThank you for applying to the Software Engineering Intern - Summer 2027 position at Initrode (R-10442). We have received your application and our recruiting team will review your background.\n\nIf your qualifications match our needs, a recruiter will reach out to you. You can check the status of your application at any time from your candidate home page."
                    + FOOT_NOREPLY
                    + "\n\nRegards,\nInitrode Talent Acquisition",
                    21,
                )
            ],
            CONF,
            APPLIED,
            "Initrode",
            "Software Engineering Intern",
        ),
        app(
            "h-wd-conf-2",
            "workday",
            [
                m(
                    "Hexagon Marine Recruiting",
                    "hexagonmarine@wd3.myworkdayjobs.com",
                    "We received your application",
                    "Dear Sam,\n\nYour application for Naval Systems Analyst Intern has been received.\n\nJob Title: Naval Systems Analyst Intern\nJob Requisition: JR-2025-4418\nLocation: Norfolk, VA\n\nThe hiring team will contact you if your profile is selected for the next stage.\n\nThank you for your interest in Hexagon Marine."
                    + FOOT_NOREPLY,
                    19,
                )
            ],
            CONF,
            APPLIED,
            "Hexagon Marine",
            "Naval Systems Analyst Intern",
        ),
        app(
            "h-wd-rej-1",
            "workday",
            [
                m(
                    "Granite Peak Careers",
                    "granitepeak@myworkday.com",
                    "Update on your application",
                    "Dear Sam,\n\nThank you for your interest in the Actuarial Intern position at Granite Peak Insurance and for the time you invested in applying.\n\nAfter reviewing your application, your application was not successful on this occasion. We wish you every success in your search."
                    + FOOT_NOREPLY,
                    6,
                )
            ],
            REJ,
            REJECTED,
            "Granite Peak Insurance",
            "Actuarial Intern",
        ),
        app(
            "h-wd-int-1",
            "workday",
            [
                m(
                    "Meridian Aerospace Talent",
                    "meridianaerospace@myworkday.com",
                    "Interview Invitation - Avionics Test Intern",
                    "Hello Sam,\n\nCongratulations! We were impressed with your application for the Avionics Test Intern role and would like to invite you to an interview.\n\nPlease sign in to your candidate home page and pick a time that works for you. Interviews last about 45 minutes and take place over video.\n\nBest regards,\nThe Meridian Aerospace Talent Acquisition Team",
                    5,
                )
            ],
            INT,
            "interview",
            "Meridian Aerospace",
            "Avionics Test Intern",
        ),
        app(
            "h-wd-off-1",
            "workday",
            [
                m(
                    "Opal Therapeutics HR",
                    "opaltherapeutics@myworkday.com",
                    "Your offer from Opal Therapeutics",
                    "Dear Sam,\n\nWe are delighted to extend an offer of employment for the Lab Automation Intern position. Your formal offer letter is attached to your candidate home page; please review and respond by December 5.\n\nWelcome aboard!\n\nWarm regards,\nOpal Therapeutics Talent Acquisition",
                    3,
                )
            ],
            OFF,
            "offer",
            "Opal Therapeutics",
            "Lab Automation Intern",
        ),
        app(
            "h-wd-conf-3",
            "workday",
            [
                m(
                    "Tundra Mobility",
                    "tundramobility@myworkday.com",
                    "Application received: Fleet Data Intern",
                    "Hi Sam,\n\nThanks for applying! Your application to Tundra Mobility for Fleet Data Intern was submitted successfully. See the details below.\n\nPosition: Fleet Data Intern\nLocation: Detroit, MI\n\nView your application: https://tundramobility.wd5.myworkdayjobs.com/en-US/Careers/job/Detroit/Fleet-Data-Intern_R-3321\n"
                    + FOOT_NOREPLY,
                    16,
                )
            ],
            CONF,
            INT,
            "Tundra Mobility",
            "Fleet Data Intern",
            "g-tundra",
        ),
    ]


def _icims_sf_taleo() -> list[Case]:
    return [
        app(
            "h-ic-conf-1",
            "icims",
            [
                m(
                    "Brightwave Networks Careers",
                    "brightwave@talent.icims.com",
                    "Brightwave Networks - Application Received",
                    "Hello Sam,\n\nWe have received your application for the Network Engineering Intern position. Thank you for your interest in a career at Brightwave Networks.\n\nOur team will review your resume and, if there is a match, contact you directly.\n\nSincerely,\nBrightwave Networks Recruiting",
                    18,
                )
            ],
            CONF,
            INT,
            "Brightwave Networks",
            "Network Engineering Intern",
            "g-brightwave",
        ),
        app(
            "h-ic-int-1",
            "icims",
            [
                m(
                    "Ironclad Logistics",
                    "ironclad@talent.icims.com",
                    "Next steps: Supply Chain Analyst Intern",
                    "Hi Sam,\n\nThanks for your patience. We'd like to move you to the next round for the Supply Chain Analyst Intern opening. Could you share your availability for a call next week? A member of our team will confirm a time.\n\nBest,\nIronclad Logistics University Recruiting",
                    9,
                )
            ],
            INT,
            "interview",
            "Ironclad Logistics",
            "Supply Chain Analyst Intern",
        ),
        app(
            "h-ic-rej-1",
            "icims",
            [
                m(
                    "Sundial Software",
                    "sundial@talent.icims.com",
                    "Your application with Sundial Software",
                    "Dear Sam,\n\nThank you for applying for the Mobile Developer Intern position. We received a large number of strong applications this year. After reviewing them, we have decided to pursue other candidates whose experience more closely matches our current needs.\n\nWe wish you the best.\n\nThe Sundial Software Talent Team"
                    + FOOT_NOREPLY,
                    7,
                )
            ],
            REJ,
            REJECTED,
            "Sundial Software",
            "Mobile Developer Intern",
        ),
        app(
            "h-ic-conf-2",
            "icims",
            [
                m(
                    "Keystone Bank Talent",
                    "keystonebank@talent.icims.com",
                    "Thank you for your application",
                    "Thank you for submitting your application for Credit Risk Intern (Req ID 88213). Keystone Bank has received your materials.\n\nIf you are selected for an interview, you will be contacted by email or phone.\n\nKeystone Bank Early Careers Team",
                    14,
                )
            ],
            CONF,
            APPLIED,
            "Keystone Bank",
            "Credit Risk Intern",
        ),
        app(
            "h-sf-conf-1",
            "successfactors",
            [
                m(
                    "Fernhill Foods Careers",
                    "noreply@successfactors.com",
                    "Thank you for your application",
                    "Dear Sam,\n\nThank you for your interest in Fernhill Foods. We have received your application for the position Food Safety Intern (ID 4471).\n\nYou will be informed about the progress of your application by email.\n\nKind regards,\nFernhill Foods Talent Acquisition",
                    17,
                )
            ],
            CONF,
            APPLIED,
            "Fernhill Foods",
            "Food Safety Intern",
        ),
        app(
            "h-sf-rej-1",
            "successfactors",
            [
                m(
                    "Pinecrest Health Careers",
                    "noreply@successfactors.com",
                    "Your application status",
                    "Dear Sam,\n\nThank you for your interest in the Clinical Informatics Intern position at Pinecrest Health. We regret to inform you that we will not be moving your application forward at this time.\n\nWe appreciate the time you took to apply.\n\nSincerely,\nPinecrest Health Talent Acquisition",
                    8,
                )
            ],
            REJ,
            REJECTED,
            "Pinecrest Health",
            "Clinical Informatics Intern",
        ),
        app(
            "h-sf-int-1",
            "successfactors",
            [
                m(
                    "Helix Genomics",
                    "noreply@successfactors.com",
                    "Invitation to interview - Bioinformatics Intern",
                    "Dear Sam,\n\nWe were pleased with your application for the Bioinformatics Intern position at Helix Genomics and would like to invite you for an interview.\n\nPlease use the link below to select a convenient time slot.\n\nKind regards,\nHelix Genomics Recruiting Team",
                    4,
                )
            ],
            INT,
            "interview",
            "Helix Genomics",
            "Bioinformatics Intern",
        ),
        app(
            "h-tl-conf-1",
            "taleo",
            [
                m(
                    "Ridgeway Consulting Careers",
                    "donotreply@taleo.net",
                    "Application Confirmation",
                    "Dear Sam,\n\nThis message confirms that we have received your application for Technology Consulting Intern (Job Number 25-0091) at Ridgeway Consulting. Your application will be reviewed and you will be contacted if you are selected for further consideration.\n\nThank you,\nRidgeway Consulting Recruiting",
                    20,
                )
            ],
            CONF,
            APPLIED,
            "Ridgeway Consulting",
            "Technology Consulting Intern",
        ),
        app(
            "h-tl-rej-1",
            "taleo",
            [
                m(
                    "Silverline Motors",
                    "donotreply@taleo.net",
                    "Status of your application",
                    "Dear Sam,\n\nThank you for your interest in Silverline Motors. We have filled the Manufacturing Engineer Intern position and will not be taking your application further. We will keep your profile on file for future openings.\n\nSilverline Motors Human Resources",
                    10,
                )
            ],
            REJ,
            REJECTED,
            "Silverline Motors",
            "Manufacturing Engineer Intern",
        ),
        app(
            "h-tl-int-1",
            "taleo",
            [
                m(
                    "Union Harbor Bank Careers",
                    "donotreply@taleo.net",
                    "Interview request - Treasury Analyst Intern",
                    "Dear Sam,\n\nYour qualifications for the Treasury Analyst Intern role at Union Harbor Bank have been reviewed and we would like to speak with you. Please reply with your availability for a phone interview next week.\n\nUnion Harbor Bank Talent Acquisition",
                    6,
                )
            ],
            INT,
            "interview",
            "Union Harbor Bank",
            "Treasury Analyst Intern",
        ),
    ]


def _gh_lever_ashby() -> list[Case]:
    gh, lv, ab = "no-reply@us.greenhouse-mail.io", "no-reply@hire.lever.co", "no-reply@ashbyhq.com"
    return [
        app(
            "h-gh-conf-1",
            "greenhouse",
            [
                m(
                    "Quillon Labs",
                    gh,
                    "Thanks for applying to Quillon Labs!",
                    "Hi Sam,\n\nThanks for applying to the Machine Learning Intern role at Quillon Labs. We've received your application and will review it shortly.\n\nIn the meantime, feel free to check out our engineering blog.\n\nBest,\nThe Quillon Labs Recruiting Team"
                    + FOOT_GH,
                    24,
                )
            ],
            CONF,
            OA,
            "Quillon Labs",
            "Machine Learning Intern",
            "g-quillon",
        ),
        app(
            "h-gh-conf-2",
            "greenhouse",
            [
                m(
                    "Larkspur Games",
                    gh,
                    "Your application to Larkspur Games",
                    "Hi Sam,\n\nYour application for Gameplay Programmer Intern has been submitted. We know applying takes time, so thank you!\n\nOur recruiters review every application. If there's a fit, we'll be in touch.\n\nLarkspur Games"
                    + FOOT_GH,
                    13,
                )
            ],
            CONF,
            APPLIED,
            "Larkspur Games",
            "Gameplay Programmer Intern",
        ),
        app(
            "h-gh-rej-1",
            "greenhouse",
            [
                m(
                    "Cobalt Security",
                    gh,
                    "An update on your Cobalt Security application",
                    "Hi Sam,\n\nThank you for taking the time to interview with us for the Security Research Intern position. It was a tough decision, but we have chosen to proceed with applicants whose skills more closely align with what we need right now.\n\nWe'd be glad to see you apply again.\n\nBest regards,\nCobalt Security Talent Team"
                    + FOOT_GH,
                    5,
                )
            ],
            REJ,
            REJECTED,
            "Cobalt Security",
            "Security Research Intern",
        ),
        app(
            "h-gh-int-1",
            "greenhouse",
            [
                m(
                    "Driftwood Studios",
                    gh,
                    "Let's chat! Animation Tools Intern at Driftwood Studios",
                    "Hi Sam,\n\nThanks for your application. We'd love to chat with you about the Animation Tools Intern role. Please pick a time that works for you using the scheduling link below and we'll send a calendar invite.\n\nLooking forward to meeting you,\nPriya, Driftwood Studios"
                    + FOOT_GH,
                    4,
                )
            ],
            INT,
            "interview",
            "Driftwood Studios",
            "Animation Tools Intern",
        ),
        app(
            "h-gh-off-1",
            "greenhouse",
            [
                m(
                    "Nimbus Cloud",
                    gh,
                    "Offer: Site Reliability Intern at Nimbus Cloud",
                    "Hi Sam,\n\nOn behalf of everyone at Nimbus Cloud, I'm thrilled to say we would like to offer you the Site Reliability Intern position for the summer. Your offer letter and compensation details are attached.\n\nPlease let me know if you have any questions.\n\nCheers,\nMaya Torres\nNimbus Cloud People Team"
                    + FOOT_GH,
                    2,
                )
            ],
            OFF,
            "offer",
            "Nimbus Cloud",
            "Site Reliability Intern",
        ),
        app(
            "h-lv-conf-1",
            "lever",
            [
                m(
                    "Copperfield Media",
                    lv,
                    "Thanks for applying to Copperfield Media",
                    "Hi Sam,\n\nThanks for your interest in Copperfield Media! We have received your application for the Video Engineering Intern position, and our team is looking at it now.\n\nIf you are a match, we'll reach out about next steps.\n\nThe Copperfield Media Team",
                    15,
                )
            ],
            CONF,
            APPLIED,
            "Copperfield Media",
            "Video Engineering Intern",
        ),
        app(
            "h-lv-int-1",
            "lever",
            [
                m(
                    "Lumen Optics",
                    lv,
                    "Lumen Optics - Intro call",
                    "Hi Sam,\n\nThank you for applying to the Optical Software Intern role. We'd like to set up a 30-minute introductory call with one of our engineers. What does your availability look like Thursday or Friday?\n\nBest,\nTom Reyes\nLumen Optics",
                    7,
                )
            ],
            INT,
            "interview",
            "Lumen Optics",
            "Optical Software Intern",
            "g-lumen",
        ),
        app(
            "h-lv-rej-1",
            "lever",
            [
                m(
                    "Orchid Pharma",
                    lv,
                    "Your application for Regulatory Affairs Intern",
                    "Hi Sam,\n\nThank you for your interest in Orchid Pharma and for the time you spent applying. We've reviewed many strong applications, and unfortunately we are not able to offer you the Regulatory Affairs Intern position at this time.\n\nBest of luck,\nOrchid Pharma Recruiting",
                    9,
                )
            ],
            REJ,
            REJECTED,
            "Orchid Pharma",
            "Regulatory Affairs Intern",
        ),
        app(
            "h-lv-conf-2",
            "lever",
            [
                m(
                    "Paragon Devices",
                    lv,
                    "We got your application!",
                    "Hello Sam,\n\nWe got your application for Firmware Intern. Thanks for putting yourself forward. Someone from Paragon Devices will review it in the next couple of weeks.\n\nTeam Paragon",
                    11,
                )
            ],
            CONF,
            APPLIED,
            "Paragon Devices",
            "Firmware Intern",
        ),
        app(
            "h-ab-conf-1",
            "ashby",
            [
                m(
                    "Vertex Harbor",
                    ab,
                    "Application received for Platform Intern",
                    "Hi Sam,\n\nThanks for applying to Vertex Harbor! This email confirms we've received your application for the Platform Intern position.\n\nWe'll keep you posted.\n\nThe Vertex Harbor Hiring Team\n\nPowered by Ashby",
                    12,
                )
            ],
            CONF,
            APPLIED,
            "Vertex Harbor",
            "Platform Intern",
        ),
        app(
            "h-ab-int-1",
            "ashby",
            [
                m(
                    "Tessellate AI",
                    ab,
                    "Tessellate AI: Next steps",
                    "Hi Sam,\n\nGood news - you've been selected to move forward for the Applied Research Intern role at Tessellate AI. Our recruiter, Jordan, will be in touch shortly to schedule a conversation.\n\nCongrats and talk soon,\nTessellate AI Talent\n\nPowered by Ashby",
                    6,
                )
            ],
            INT,
            "interview",
            "Tessellate AI",
            "Applied Research Intern",
            "g-tessellate",
        ),
        app(
            "h-ab-rej-1",
            "ashby",
            [
                m(
                    "Borealis Energy",
                    ab,
                    "Your application to Borealis Energy",
                    "Hi Sam,\n\nThank you for your interest in the Grid Analytics Intern role. After careful consideration, we've decided not to move forward with your application at this stage. This was a very competitive pool.\n\nWishing you all the best,\nBorealis Energy Talent Acquisition\n\nPowered by Ashby",
                    8,
                )
            ],
            REJ,
            REJECTED,
            "Borealis Energy",
            "Grid Analytics Intern",
        ),
    ]


def _sr_workable_boards() -> list[Case]:
    sr, wk = "no-reply@smartrecruiters.com", "no-reply@workable.com"
    li, ind, hs = (
        "jobs-noreply@linkedin.com",
        "indeedapply@indeed.com",
        "no-reply@joinhandshake.com",
    )
    return [
        app(
            "h-sr-conf-1",
            "smartrecruiters",
            [
                m(
                    "Saffron Kitchen Tech",
                    sr,
                    "Your application to Saffron Kitchen Tech was received",
                    "Hi Sam,\n\nThank you for applying. Your application for the Backend Engineer Intern job at Saffron Kitchen Tech has been received.\n\nJob ID: 7421993\n\nWe will contact you if there is a match.\n\nBest regards,\nSaffron Kitchen Tech Recruiting Team",
                    22,
                )
            ],
            CONF,
            APPLIED,
            "Saffron Kitchen Tech",
            "Backend Engineer Intern",
        ),
        app(
            "h-sr-rej-1",
            "smartrecruiters",
            [
                m(
                    "Willow Education",
                    sr,
                    "Update regarding your application",
                    "Hello Sam,\n\nThank you for your interest in Willow Education. We regret to inform you that we have decided not to continue with your application for the Learning Experience Intern job.\n\nWe appreciate your interest and wish you every success.\n\nWillow Education Talent Acquisition",
                    10,
                )
            ],
            REJ,
            REJECTED,
            "Willow Education",
            "Learning Experience Intern",
        ),
        app(
            "h-sr-int-1",
            "smartrecruiters",
            [
                m(
                    "Northstar Airlines",
                    sr,
                    "Northstar Airlines - interview invitation",
                    "Hi Sam,\n\nWe've reviewed your application for the Revenue Management Intern job and we'd love to talk to you. Please use the link to choose a time for a video interview with our team.\n\nThanks,\nNorthstar Airlines University Recruiting",
                    5,
                )
            ],
            INT,
            "interview",
            "Northstar Airlines",
            "Revenue Management Intern",
            "g-northstar",
        ),
        app(
            "h-wk-conf-1",
            "workable",
            [
                m(
                    "Mosaic Retail",
                    wk,
                    "Thanks for applying to Mosaic Retail",
                    "Hi Sam,\n\nThank you for applying to the E-commerce Analyst Intern position at Mosaic Retail. We have received your application and are reviewing it.\n\nGood luck!\nMosaic Retail Hiring Team\n\nSent via Workable",
                    14,
                )
            ],
            CONF,
            APPLIED,
            "Mosaic Retail",
            "E-commerce Analyst Intern",
        ),
        app(
            "h-wk-rej-1",
            "workable",
            [
                m(
                    "Quartz Interactive",
                    wk,
                    "Your application to Quartz Interactive",
                    "Hi Sam,\n\nThank you for your interest in the UX Engineer Intern position at Quartz Interactive. We've decided to go with other candidates for this role, but we were impressed by your portfolio.\n\nAll the best,\nQuartz Interactive\n\nSent via Workable",
                    9,
                )
            ],
            REJ,
            REJECTED,
            "Quartz Interactive",
            "UX Engineer Intern",
        ),
        app(
            "h-wk-int-1",
            "workable",
            [
                m(
                    "Marlow & Finch",
                    wk,
                    "Marlow & Finch: let's schedule a call",
                    "Hi Sam,\n\nThanks for applying for the Associate Analyst Intern role at Marlow & Finch. We would like to schedule a call to learn more about your experience. Are you free for 20 minutes on Monday?\n\nRegards,\nElena Park\nMarlow & Finch",
                    3,
                )
            ],
            INT,
            "interview",
            "Marlow & Finch",
            "Associate Analyst Intern",
            "g-marlow",
        ),
        app(
            "h-li-conf-1",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Sam, your application was sent to Copperfield Media",
                    "Your application was sent to Copperfield Media\n\nSoftware Engineer Intern\nCopperfield Media - Austin, TX (Hybrid)\n\nApplied on Nov 3\n\nSee similar jobs\n\nYou are receiving LinkedIn job alert emails. Unsubscribe or manage your job alerts here.",
                    24,
                )
            ],
            CONF,
            APPLIED,
            "Copperfield Media",
            "Software Engineer Intern",
        ),
        app(
            "h-li-conf-2",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    li,
                    "Your application to Redwood Credit Union",
                    "Your application was sent to Redwood Credit Union\n\nData Analyst Intern\nRedwood Credit Union - Sacramento, CA (On-site)\n\nGood luck! Companies typically respond within a week.\n\nUnsubscribe from job alerts",
                    18,
                )
            ],
            CONF,
            INT,
            "Redwood Credit Union",
            "Data Analyst Intern",
            "g-redwood",
        ),
        app(
            "h-li-rej-1",
            "linkedin",
            [
                m(
                    "LinkedIn",
                    "jobs-noreply@linkedin.com",
                    "Your update from Fernhill Foods",
                    "Hi Sam,\n\nThank you for your interest in the Quality Analyst Intern position at Fernhill Foods. Unfortunately, they are moving forward with other candidates.\n\nKeep exploring: see more Quality jobs on LinkedIn.",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Fernhill Foods",
            "Quality Analyst Intern",
        ),
        app(
            "h-in-conf-1",
            "indeed",
            [
                m(
                    "Indeed Apply",
                    ind,
                    "Indeed Application: Operations Intern",
                    "Application submitted\n\nOperations Intern\nWestbrook Hospitality - Chicago, IL\n\nThe following items were sent to Westbrook Hospitality. Good luck!\n\n- Application\n- Resume\n\nUnsubscribe from job alert emails | Indeed privacy policy",
                    19,
                )
            ],
            CONF,
            INT,
            "Westbrook Hospitality",
            "Operations Intern",
            "g-westbrook",
        ),
        app(
            "h-in-int-1",
            "indeed",
            [
                m(
                    "Indeed",
                    ind,
                    "Interview request from Evergreen Dental Group",
                    "Hi Sam,\n\nEvergreen Dental Group would like to schedule an interview with you for the Dental Practice Analyst Intern position. Please reply to choose a day and time that suits you.\n\nThis message was sent through Indeed. Manage your Indeed notification settings.",
                    6,
                )
            ],
            INT,
            "interview",
            "Evergreen Dental Group",
            "Dental Practice Analyst Intern",
            "g-evergreen",
        ),
        app(
            "h-in-rej-1",
            "indeed",
            [
                m(
                    "Indeed",
                    ind,
                    "Update on your application to Crescent Bay Hotels",
                    "Hello Sam,\n\nThank you for applying to the Revenue Intern job at Crescent Bay Hotels. They have chosen to move forward with other applicants and your application is no longer being considered.\n\nSee jobs similar to this one on Indeed.",
                    7,
                )
            ],
            REJ,
            REJECTED,
            "Crescent Bay Hotels",
            "Revenue Intern",
        ),
        app(
            "h-hs-conf-1",
            "handshake",
            [
                m(
                    "Handshake",
                    hs,
                    "You've applied to Data Engineering Intern at Mosaic Retail",
                    "Hi Sam,\n\nYou've successfully applied to the Data Engineering Intern position at Mosaic Retail through Handshake. The employer will review your application and may reach out directly.\n\nYou can view your applications anytime in your Handshake account. Unsubscribe from these emails.",
                    17,
                )
            ],
            CONF,
            APPLIED,
            "Mosaic Retail",
            "Data Engineering Intern",
        ),
        app(
            "h-hs-int-1",
            "handshake",
            [
                m(
                    "Handshake",
                    hs,
                    "Willow Education wants to interview you",
                    "Hi Sam,\n\nWillow Education has invited you to interview for the Curriculum Data Intern role. Log in to Handshake to accept the invitation and choose a time slot.\n\nUnsubscribe from these emails.",
                    5,
                )
            ],
            INT,
            "interview",
            "Willow Education",
            "Curriculum Data Intern",
        ),
        app(
            "h-hs-rej-1",
            "handshake",
            [
                m(
                    "Handshake",
                    hs,
                    "Application update from Juniper Systems",
                    "Hi Sam,\n\nJuniper Systems has reviewed your application for the Systems Test Intern position and has decided not to move forward at this time. You can keep applying to roles on Handshake.\n\nUnsubscribe from these emails.",
                    8,
                )
            ],
            REJ,
            REJECTED,
            "Juniper Systems",
            "Systems Test Intern",
        ),
    ]


def _direct_recruiter_cal() -> list[Case]:
    return [
        app(
            "h-dir-conf-1",
            "direct",
            [
                m(
                    "Halcyon Bio Careers",
                    "careers@halcyon-bio.example",
                    "Application received - Research Associate Intern",
                    "Dear Sam,\n\nYour application has been submitted. Thanks for your interest in joining Halcyon Bio!\n\nPosition applied for: Research Associate Intern\nApplication date: November 2\n\nOur talent team will be in touch if your profile fits.\n\nBest regards,\nHalcyon Bio Talent Acquisition Team",
                    22,
                )
            ],
            CONF,
            APPLIED,
            "Halcyon Bio",
            "Research Associate Intern",
        ),
        app(
            "h-dir-conf-2",
            "direct",
            [
                m(
                    "Oakridge Capital",
                    "no-reply@oakridgecapital.example",
                    "Thanks for applying!",
                    "Hi Sam,\n\nThis is an automatic confirmation that we've received your application to our Summer Analyst program. There is no need to reply.\n\nThank you for your interest in Oakridge Capital.\n\nThe Oakridge Capital Campus Recruiting Team",
                    20,
                )
            ],
            CONF,
            APPLIED,
            "Oakridge Capital",
            "Summer Analyst",
        ),
        app(
            "h-dir-rej-1",
            "direct",
            [
                m(
                    "Meridian Aerospace",
                    "recruiting@meridian-aero.example",
                    "Regarding your application",
                    "Dear Sam,\n\nThank you for your interest in Meridian Aerospace and for taking the time to speak with our team. We have decided not to extend an offer for the Propulsion Intern position. This was a difficult decision given the strength of the pool.\n\nWe wish you well in your search.\n\nSincerely,\nMeridian Aerospace University Recruiting",
                    4,
                )
            ],
            REJ,
            REJECTED,
            "Meridian Aerospace",
            "Propulsion Intern",
        ),
        app(
            "h-dir-int-1",
            "direct",
            [
                m(
                    "Westbrook Hospitality",
                    "talent@westbrook-hospitality.example",
                    "Invitation to interview",
                    "Hi Sam,\n\nThank you for applying to Westbrook Hospitality. We'd like to invite you to a first-round interview for the Operations Intern role. The interview will be held on Zoom and lasts about 30 minutes.\n\nPlease reply with two times that work for you.\n\nBest,\nWestbrook Hospitality Talent Team",
                    10,
                )
            ],
            INT,
            "interview",
            "Westbrook Hospitality",
            "Operations Intern",
            "g-westbrook",
        ),
        app(
            "h-dir-off-1",
            "direct",
            [
                m(
                    "Crescent Bay Hotels",
                    "hr@crescentbay-hotels.example",
                    "Congratulations from Crescent Bay Hotels",
                    "Dear Sam,\n\nCongratulations! We are pleased to offer you the position of Guest Analytics Intern at Crescent Bay Hotels. A formal offer letter will follow by email within two business days.\n\nWelcome to the team!\n\nBest wishes,\nCrescent Bay Hotels Human Resources",
                    3,
                )
            ],
            OFF,
            "offer",
            "Crescent Bay Hotels",
            "Guest Analytics Intern",
        ),
        app(
            "h-rr-int-1",
            "recruiter",
            [
                m(
                    "Elena Park",
                    "elena.park@marlowfinch.example",
                    "Marlow & Finch - Associate Analyst Intern",
                    "Hi Sam,\n\nI'm a recruiter at Marlow & Finch. I saw your application for the Associate Analyst Intern position and would like to set up a time to talk. Are you free Wednesday afternoon for a quick video call?\n\nThanks,\nElena Park\nTalent Partner, Marlow & Finch\nelena.park@marlowfinch.example | 555-0142",
                    8,
                ),
            ],
            INT,
            "interview",
            "Marlow & Finch",
            "Associate Analyst Intern",
            "g-marlow",
        ),
        app(
            "h-rr-int-2",
            "recruiter",
            [
                m(
                    "Luis Ortega",
                    "luis.ortega@evergreendental.example",
                    "Evergreen Dental Group - next steps",
                    "Hi Sam,\n\nThanks for your interest in the Dental Practice Analyst Intern opening at Evergreen Dental Group. We'd like to move you forward to a conversation with the practice manager. When are you available this week?\n\nBest,\nLuis",
                    5,
                ),
            ],
            INT,
            "interview",
            "Evergreen Dental Group",
            "Dental Practice Analyst Intern",
            "g-evergreen",
        ),
        app(
            "h-cal-int-1",
            "calendar",
            [
                m(
                    "Brightwave Networks Recruiting",
                    "calendar-notification@google.com",
                    "Invitation: Brightwave Networks interview - Sam Student @ Tue Dec 2, 2pm - 2:45pm (PST)",
                    "Brightwave Networks interview - Sam Student\n\nWhen: Tuesday Dec 2, 2pm - 2:45pm (Pacific Time)\nWhere: https://meet.example/abc-defg-hij\nOrganizer: recruiting@brightwave.example\n\nInvitation from Google Calendar. You are receiving this email because you are an attendee of the event.",
                    2,
                )
            ],
            INT,
            "interview",
            "Brightwave Networks",
            None,
            "g-brightwave",
        ),
        app(
            "h-cal-int-2",
            "calendar",
            [
                m(
                    "Calendly",
                    "notifications@calendly.com",
                    "Confirmed: Intro call with Northstar Airlines University Recruiting",
                    "Your event is confirmed\n\nIntro call with Northstar Airlines University Recruiting\nMonday, December 1, 10:00am - 10:30am\nHost: Maya Torres\n\nNeed to make changes? Reschedule or cancel. Powered by Calendly.",
                    3,
                )
            ],
            INT,
            "interview",
            "Northstar Airlines",
            None,
            "g-northstar",
        ),
        app(
            "h-cal-int-3",
            "calendar",
            [
                m(
                    "GoodTime",
                    "no-reply@goodtime.io",
                    "Your interview with Tundra Mobility is scheduled",
                    "Hi Sam,\n\nYour interview with Tundra Mobility for the Fleet Data Intern role is scheduled for Wednesday at 1:00pm Eastern. You will meet with two members of the data team over video.\n\nNeed another time? Use the reschedule link. Scheduled with GoodTime.",
                    4,
                )
            ],
            INT,
            "interview",
            "Tundra Mobility",
            "Fleet Data Intern",
            "g-tundra",
        ),
        app(
            "h-oa-hr-1",
            "hackerrank",
            [
                m(
                    "HackerRank",
                    "no-reply@hackerrank.com",
                    "Tessellate AI has invited you to take a coding test",
                    "Hi Sam,\n\nTessellate AI has invited you to take the Applied Research Intern Screening test on HackerRank. The test has 3 questions and must be completed within 90 minutes of starting.\n\nStart test: https://www.hackerrank.com/tests/abcdef\n\nGood luck!\nThe HackerRank Team",
                    5,
                )
            ],
            OA,
            INT,
            "Tessellate AI",
            None,
            "g-tessellate",
        ),
        app(
            "h-oa-cs-1",
            "codesignal",
            [
                m(
                    "CodeSignal",
                    "no-reply@codesignal.com",
                    "Quillon Labs invited you to complete a coding assessment",
                    "Hello Sam,\n\nQuillon Labs has invited you to take the General Coding Assessment for their Machine Learning Intern role. You have 70 minutes once you begin. The assessment link expires in 7 days.\n\nBegin assessment\n\nCodeSignal, Inc.",
                    18,
                )
            ],
            OA,
            "online_assessment",
            "Quillon Labs",
            "Machine Learning Intern",
            "g-quillon",
        ),
        app(
            "h-oa-cod-1",
            "codility",
            [
                m(
                    "Codility",
                    "no-reply@codility.com",
                    "Lumen Optics: your Codility coding test",
                    "Hi Sam,\n\nYou have been invited by Lumen Optics to take an online coding test as part of the Optical Software Intern application process. The test takes about 60 minutes.\n\nStart your test: https://app.codility.com/c/run/xyz\n\nGood luck!",
                    6,
                )
            ],
            OA,
            INT,
            "Lumen Optics",
            "Optical Software Intern",
            "g-lumen",
        ),
        app(
            "h-oa-hv-1",
            "hirevue",
            [
                m(
                    "HireVue",
                    "no-reply@hirevue.com",
                    "Redwood Credit Union: complete your HireVue interview",
                    "Hello Sam,\n\nRedwood Credit Union has invited you to complete a digital HireVue interview for the Data Analyst Intern position. You can record your answers at any time before December 12.\n\nStart interview\n\nHireVue, Inc.",
                    3,
                )
            ],
            INT,
            "interview",
            "Redwood Credit Union",
            "Data Analyst Intern",
            "g-redwood",
        ),
    ]


def _threads() -> list[Case]:
    gh, lv = "no-reply@us.greenhouse-mail.io", "no-reply@hire.lever.co"
    sam = "Sam Student"
    return [
        app(
            "h-g1-conf",
            "multi",
            [
                m(
                    "Kestrel Analytics",
                    gh,
                    "Thank you for applying to Kestrel Analytics",
                    "Hi Sam,\n\nThank you for applying to the Data Engineer Intern role at Kestrel Analytics. We've received your application.\n\nBest,\nThe Kestrel Analytics Recruiting Team"
                    + FOOT_GH,
                    29,
                )
            ],
            CONF,
            REJECTED,
            "Kestrel Analytics",
            "Data Engineer Intern",
            "g-kestrel",
        ),
        app(
            "h-g1-int",
            "multi",
            [
                m(
                    "Rosa Delgado",
                    "rosa.delgado@kestrelanalytics.example",
                    "Kestrel Analytics - Data Engineer Intern interview",
                    "Hi Sam,\n\nI'd like to schedule an interview for the Data Engineer Intern position at Kestrel Analytics. Please let me know which of these slots suits you: Tue 10am, Wed 3pm, Thu 11am.\n\nBest,\nRosa Delgado\nUniversity Recruiter, Kestrel Analytics",
                    24,
                )
            ],
            INT,
            REJECTED,
            "Kestrel Analytics",
            "Data Engineer Intern",
            "g-kestrel",
        ),
        app(
            "h-g1-rej",
            "multi",
            [
                m(
                    "Kestrel Analytics",
                    gh,
                    "Update from Kestrel Analytics",
                    "Hi Sam,\n\nThank you for interviewing for the Data Engineer Intern role. After careful consideration, we have decided to move forward with other candidates for this position.\n\nWe appreciate your time.\n\nKestrel Analytics Recruiting Team"
                    + FOOT_GH,
                    9,
                )
            ],
            REJ,
            REJECTED,
            "Kestrel Analytics",
            "Data Engineer Intern",
            "g-kestrel",
        ),
        app(
            "h-g2-conf",
            "multi",
            [
                m(
                    "Silverline Motors",
                    lv,
                    "Thanks for applying to Silverline Motors",
                    "Hi Sam,\n\nThanks for applying for the Embedded Software Intern position. We have received your application.\n\nSilverline Motors Talent Team",
                    30,
                )
            ],
            CONF,
            INT,
            "Silverline Motors",
            "Embedded Software Intern",
            "g-silverline",
        ),
        app(
            "h-g2-oa",
            "multi",
            [
                m(
                    "Codility",
                    "no-reply@codility.com",
                    "Silverline Motors: Codility test invitation",
                    "Hi Sam,\n\nSilverline Motors has sent you a coding test for the Embedded Software Intern position. You have 7 days to complete the test.\n\nStart your test: https://app.codility.com/c/run/abc",
                    24,
                )
            ],
            OA,
            INT,
            "Silverline Motors",
            "Embedded Software Intern",
            "g-silverline",
        ),
        app(
            "h-g2-int",
            "multi",
            [
                m(
                    "Greta Lindqvist",
                    "greta.lindqvist@silverline-motors.example",
                    "Embedded Software Intern - next steps",
                    "Hi Sam,\n\nCongratulations on passing the coding test! We would like to invite you to an interview for the Embedded Software Intern position. Please pick a time here: https://silverline-motors.example/schedule/abc\n\nBest regards,\nGreta Lindqvist\nSilverline Motors Talent Acquisition",
                    12,
                )
            ],
            INT,
            INT,
            "Silverline Motors",
            "Embedded Software Intern",
            "g-silverline",
        ),
        app(
            "h-g3-li",
            "multi",
            [
                m(
                    "LinkedIn",
                    "jobs-noreply@linkedin.com",
                    "Your application to Pinecrest Health",
                    "Your application was sent to Pinecrest Health\n\nBusiness Analyst Intern\nPinecrest Health - Minneapolis, MN\n\nApplied on Oct 29\n\nUnsubscribe from job alerts",
                    27,
                )
            ],
            CONF,
            APPLIED,
            "Pinecrest Health",
            "Business Analyst Intern",
            "g-pinecrest",
        ),
        app(
            "h-g3-wd",
            "multi",
            [
                m(
                    "Pinecrest Health Careers",
                    "pinecresthealth@myworkday.com",
                    "Thank you for applying",
                    "Hi Sam,\n\nThank you for applying to the Business Analyst Intern position at Pinecrest Health. Your application has been received and will be reviewed by our team.\n\nRegards,\nPinecrest Health Talent Acquisition",
                    26,
                )
            ],
            CONF,
            APPLIED,
            "Pinecrest Health",
            "Business Analyst Intern",
            "g-pinecrest",
        ),
        app(
            "h-mt-1",
            "multi",
            [
                m(
                    "Priya Natarajan",
                    "priya.natarajan@juniper-systems.example",
                    "Cloud Engineer Intern at Juniper Systems",
                    "Hi Sam,\n\nWe'd like to invite you to interview for the Cloud Engineer Intern role at Juniper Systems. Would Thursday at 2pm Eastern work?\n\nThanks,\nPriya Natarajan\nJuniper Systems Recruiting",
                    10,
                ),
                m(
                    sam,
                    ME,
                    "Re: Cloud Engineer Intern at Juniper Systems",
                    "Hi Priya,\n\nThursday at 2pm works for me. Thank you!\n\nSam",
                    9,
                    user=True,
                ),
                m(
                    "Priya Natarajan",
                    "priya.natarajan@juniper-systems.example",
                    "Re: Cloud Engineer Intern at Juniper Systems",
                    "Great, I'll send a calendar invite shortly.\n\nPriya\n\nOn Tue, Nov 11, Sam Student <sam.student@mail.example> wrote:\n> Hi Priya,\n> Thursday at 2pm works for me. Thank you!",
                    8,
                ),
            ],
            INT,
            INT,
            "Juniper Systems",
            "Cloud Engineer Intern",
        ),
        app(
            "h-mt-2",
            "multi",
            [
                m(
                    "Tundra Mobility",
                    "no-reply@us.greenhouse-mail.io",
                    "Your Tundra Mobility application",
                    "Hi Sam,\n\nThanks for applying to Tundra Mobility. We received your application for the Controls Engineer Intern role.\n\nTundra Mobility Recruiting"
                    + FOOT_GH,
                    20,
                ),
                m(
                    "Tundra Mobility",
                    "no-reply@us.greenhouse-mail.io",
                    "Your Tundra Mobility application",
                    "Hi Sam,\n\nWe would like to invite you for an interview for the Controls Engineer Intern role. Please schedule your interview using the link below.\n\nTundra Mobility Recruiting"
                    + FOOT_GH,
                    12,
                ),
                m(
                    "Tundra Mobility",
                    "no-reply@us.greenhouse-mail.io",
                    "Your Tundra Mobility application",
                    "Hi Sam,\n\nThis is a friendly reminder to schedule your interview. Your invitation link expires on Friday.\n\nTundra Mobility Recruiting"
                    + FOOT_GH,
                    7,
                ),
            ],
            INT,
            INT,
            "Tundra Mobility",
            "Controls Engineer Intern",
        ),
        app(
            "h-mt-3",
            "multi",
            [
                m(
                    "Ironclad Logistics",
                    "no-reply@us.greenhouse-mail.io",
                    "Ironclad Logistics: Operations Research Intern",
                    "Hi Sam,\n\nThank you for applying for the Operations Research Intern position at Ironclad Logistics. After reviewing your application we are not moving forward with your candidacy at this time.\n\nIronclad Logistics Recruiting"
                    + FOOT_GH,
                    14,
                ),
                m(
                    "Ironclad Logistics",
                    "no-reply@us.greenhouse-mail.io",
                    "Ironclad Logistics: Operations Research Intern",
                    "Hi Sam,\n\nWe noticed you haven't been able to take a look at our message. Please reply if you have any questions about your application.\n\nIronclad Logistics Recruiting"
                    + FOOT_GH,
                    6,
                ),
            ],
            REJ,
            REJECTED,
            "Ironclad Logistics",
            "Operations Research Intern",
        ),
    ]


def _recruiters() -> list[Case]:
    return [
        rec(
            "h-rec-1",
            "recruiter",
            [
                m(
                    "Nadia Okafor",
                    "nadia@talentbridge-search.example",
                    "Opportunity at a fintech startup",
                    "Hi Sam,\n\nI came across your profile and was impressed by your projects. I'm reaching out about a full-stack role at a Series B fintech startup. Would you be open to a quick chat?\n\nBest,\nNadia",
                    11,
                )
            ],
        ),
        rec(
            "h-rec-2",
            "recruiter",
            [
                m(
                    "Ben Whitaker",
                    "ben.whitaker@orchid-pharma.example",
                    "Quick question",
                    "Hello Sam,\n\nI'm a sourcer at Orchid Pharma. We're building out our data team and your background caught my attention. Are you interested in learning more about our internship program?\n\nBen",
                    12,
                )
            ],
        ),
        rec(
            "h-rec-3",
            "recruiter",
            [
                m(
                    "Talent Partners",
                    "outreach@staffingco.example",
                    "Exciting internship roles in your area",
                    "Hi Sam,\n\nI am reaching out about several internship roles that could be a great fit for you. Would you be open to sharing an updated resume so I can match you?\n\nRegards,\nStaffingCo Team",
                    13,
                )
            ],
        ),
    ]


def _noise() -> list[Case]:
    return [
        noise(
            "h-n-alert-1",
            "noise.job_alert",
            [
                m(
                    "LinkedIn Job Alerts",
                    "jobalerts-noreply@linkedin.com",
                    '"data analyst intern": Redwood Credit Union and 18 more new jobs',
                    "Your job alert for data analyst intern in United States.\n18 new jobs match your preferences.\nRedwood Credit Union - Data Analyst Intern\nSee all jobs\nYou are receiving job alert emails. Manage your job alerts.",
                    2,
                )
            ],
        ),
        noise(
            "h-n-alert-2",
            "noise.job_alert",
            [
                m(
                    "Indeed",
                    "alert@indeed.com",
                    "Your application may stand out: 9 new internships for you",
                    "Hi Sam,\n\nHere are new internships we think you'll like.\nOperations Intern - Westbrook Hospitality\nResearch Intern - Halcyon Bio\nApply now with your Indeed resume.\n\nUnsubscribe from this job alert",
                    3,
                )
            ],
        ),
        noise(
            "h-n-alert-3",
            "noise.job_alert",
            [
                m(
                    "Glassdoor",
                    "noreply@glassdoor.com",
                    "Interview questions for Sundial Software are trending",
                    "Hi Sam,\n\nPeople interviewing at Sundial Software are sharing questions about the Software Engineer Intern interview. See what candidates are saying.\n\nUnsubscribe from Glassdoor emails.",
                    4,
                )
            ],
        ),
        noise(
            "h-n-news-1",
            "noise.newsletter",
            [
                m(
                    "The Intern Insider",
                    "hello@internsinsider.example",
                    "5 tips to ace your next interview",
                    "Hey there,\n\nThis week: how to answer 'tell me about yourself', how to follow up after an interview, and our favorite coding challenge platforms for practice.\n\nRead online | Unsubscribe",
                    5,
                )
            ],
        ),
        noise(
            "h-n-news-2",
            "noise.newsletter",
            [
                m(
                    "Campus Careers Weekly",
                    "weekly@campuscareers.example",
                    "This week in internships: offers are rolling in",
                    "Good morning!\n\nWe analysed thousands of offers this season. Which employers are making offers earliest? Plus: how to negotiate your first offer letter.\n\nYou are receiving this because you subscribed. Unsubscribe.",
                    6,
                )
            ],
        ),
        noise(
            "h-n-news-3",
            "noise.newsletter",
            [
                m(
                    "Dev Weekly",
                    "editor@devweekly.example",
                    "Dev Weekly #412: a new assessment tool for hiring managers",
                    "Hi,\n\nThis issue covers a new online assessment product for hiring teams, Rust 2.0 notes, and a take-home project template.\n\nUnsubscribe | View in browser",
                    7,
                )
            ],
        ),
        noise(
            "h-n-school-1",
            "noise.school",
            [
                m(
                    "University Career Center",
                    "careercenter@university.example",
                    "Career Fair next Thursday - bring your resume",
                    "Dear students,\n\nThe Fall Career Fair takes place next Thursday in the Student Union. More than 90 employers will be hiring interns. Bring printed copies of your resume.\n\nCareer Center",
                    5,
                )
            ],
        ),
        noise(
            "h-n-school-2",
            "noise.school",
            [
                m(
                    "Registrar",
                    "registrar@university.example",
                    "Your spring course registration window",
                    "Hi Sam,\n\nYour registration window opens on December 3 at 8:00am. Please meet with your advisor before then.\n\nOffice of the Registrar",
                    8,
                )
            ],
        ),
        noise(
            "h-n-school-3",
            "noise.school",
            [
                m(
                    "Professor Alvarez",
                    "alvarez@university.example",
                    "Re: recommendation letter for internship applications",
                    "Hi Sam,\n\nHappy to write the letter. Can you send me the list of internship positions you are applying to and your resume by Friday?\n\nBest,\nProf. Alvarez",
                    9,
                )
            ],
        ),
        noise(
            "h-n-li-1",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    "notifications-noreply@linkedin.com",
                    "Sam, you appeared in 14 searches this week",
                    "Hi Sam,\n\nYou appeared in 14 searches this week. See who is looking at your profile. Recruiters from 3 companies viewed your profile.\n\nUnsubscribe",
                    3,
                )
            ],
        ),
        noise(
            "h-n-li-2",
            "noise.linkedin",
            [
                m(
                    "LinkedIn",
                    "invitations@linkedin.com",
                    "Mia Chen wants to connect",
                    "Hi Sam,\n\nMia Chen, Talent Acquisition Specialist at Kestrel Analytics, wants to connect with you on LinkedIn.\n\nAccept | View profile\n\nUnsubscribe",
                    4,
                )
            ],
        ),
        noise(
            "h-n-cal-1",
            "noise.calendar",
            [
                m(
                    "Alex Kim",
                    "calendar-notification@google.com",
                    "Invitation: Study group @ Thu Dec 4, 6pm - 7pm (PST)",
                    "Study group\n\nWhen: Thursday Dec 4, 6pm - 7pm\nWhere: Library room 3\nOrganizer: alex.kim@mail2.example\n\nInvitation from Google Calendar.",
                    2,
                )
            ],
        ),
        noise(
            "h-n-cal-2",
            "noise.calendar",
            [
                m(
                    "Calendly",
                    "notifications@calendly.com",
                    "Confirmed: Haircut with Joe's Barbershop",
                    "Your event is confirmed\n\nHaircut with Joe's Barbershop\nSaturday, December 6, 11:00am\n\nPowered by Calendly.",
                    3,
                )
            ],
        ),
        noise(
            "h-n-misc-1",
            "noise.misc",
            [
                m(
                    "Spotify",
                    "no-reply@spotify.example",
                    "Your Wrapped is here",
                    "Hi Sam,\n\nYour year in music is ready. See your top artists and songs.\n\nUnsubscribe",
                    4,
                )
            ],
        ),
        noise(
            "h-n-misc-2",
            "noise.receipt",
            [
                m(
                    "Campus Bookstore",
                    "orders@bookstore.example",
                    "Your order has shipped",
                    "Hi Sam,\n\nYour order #55812 (Algorithms textbook) has shipped and should arrive by Friday.\n\nTrack your package",
                    5,
                )
            ],
        ),
        noise(
            "h-n-misc-3",
            "noise.misc",
            [
                m(
                    "Mom",
                    "mom@family.example",
                    "Good luck with your interviews!",
                    "Hi sweetie,\n\nDad and I are so proud of you. Good luck with your interviews this week! Call us Sunday.\n\nLove, Mom",
                    2,
                )
            ],
        ),
        noise(
            "h-n-misc-4",
            "noise.misc",
            [
                m(
                    "Coursera",
                    "no-reply@coursera.example",
                    "Complete your assessment to earn your certificate",
                    "Hi Sam,\n\nYou are one step away from your Data Structures certificate. Complete the final assessment by December 10.\n\nUnsubscribe",
                    6,
                )
            ],
        ),
        noise(
            "h-n-misc-5",
            "noise.misc",
            [
                m(
                    "Orchid Pharma Events",
                    "events@orchid-pharma.example",
                    "Join our virtual open house for students",
                    "Hello students,\n\nJoin Orchid Pharma for a virtual open house on December 9. Meet our recruiters and learn about careers in pharma. Register today.\n\nUnsubscribe",
                    7,
                )
            ],
        ),
        noise(
            "h-n-ats-1",
            "noise.ats_account",
            [
                m(
                    "Greenhouse",
                    "no-reply@us.greenhouse-mail.io",
                    "Confirm your email address",
                    "Hi Sam,\n\nPlease confirm your email address to finish creating your candidate account. Click the button below to verify.\n\nIf you did not create this account you can ignore this email.",
                    15,
                )
            ],
        ),
        noise(
            "h-n-ats-2",
            "noise.ats_account",
            [
                m(
                    "Workday",
                    "mosaicretail@myworkday.com",
                    "Your password was changed",
                    "Hi Sam,\n\nThe password for your Mosaic Retail candidate account was changed. If you did not make this change, contact support.\n\nThis is an automated message, please do not reply.",
                    14,
                )
            ],
        ),
        noise(
            "h-n-misc-6",
            "noise.misc",
            [
                m(
                    "Strava",
                    "no-reply@strava.example",
                    "You hit a new personal best",
                    "Congrats Sam, you ran your fastest 5k yet. See your stats.\n\nUnsubscribe",
                    3,
                )
            ],
        ),
        noise(
            "h-n-misc-7",
            "noise.misc",
            [
                m(
                    "Your Bank",
                    "alerts@bank.example",
                    "Statement available",
                    "Hi Sam,\n\nYour November statement is ready to view in online banking.\n\nSecure message from your bank.",
                    6,
                )
            ],
        ),
    ]


def _more() -> list[Case]:
    return [
        app(
            "h-dir-conf-3",
            "direct",
            [
                m(
                    "Zephyr Wind Power",
                    "jobs@zephyrwind.example",
                    "Your application has been received",
                    "Hi Sam,\n\nThanks for your application. Here is a summary of what you submitted.\n\nJob: Turbine Data Intern\nLocation: Denver, CO\nReference: ZW-1187\n\nOur hiring team will review it and get back to you within two weeks.\n\nThe Zephyr Wind Power Hiring Team",
                    16,
                )
            ],
            CONF,
            APPLIED,
            "Zephyr Wind Power",
            "Turbine Data Intern",
        ),
        app(
            "h-ic-off-1",
            "icims",
            [
                m(
                    "Atlas Freight Careers",
                    "atlasfreight@talent.icims.com",
                    "Your offer from Atlas Freight",
                    "Dear Sam,\n\nCongratulations! Atlas Freight is delighted to offer you the Logistics Analyst Intern position starting June 8. Please review the attached offer letter and respond by December 12.\n\nWe look forward to welcoming you.\n\nSincerely,\nAtlas Freight Talent Acquisition",
                    2,
                )
            ],
            OFF,
            "offer",
            "Atlas Freight",
            "Logistics Analyst Intern",
        ),
        app(
            "h-gh-conf-3",
            "greenhouse",
            [
                m(
                    "Blue Harbor",
                    "no-reply@us.greenhouse-mail.io",
                    "Application received - Quantitative Research Intern",
                    "Hi Sam,\n\nWe have received your application for the Quantitative Research Intern role. Thanks for your interest in working with us!\n\nWarm regards,\nBlue Harbor Recruiting"
                    + FOOT_GH,
                    12,
                )
            ],
            CONF,
            APPLIED,
            "Blue Harbor",
            "Quantitative Research Intern",
        ),
        app(
            "h-wd-oa-1",
            "workday",
            [
                m(
                    "Arbor Logistics",
                    "arborlogistics@wd1.myworkdayjobs.com",
                    "Next step: online assessment",
                    "Hi Sam,\n\nThank you for applying to the Process Engineer Intern role at Arbor Logistics. As the next step, please complete the online assessment within 5 days using the link below.\n\nThe assessment takes about 40 minutes."
                    + FOOT_NOREPLY,
                    6,
                )
            ],
            OA,
            "online_assessment",
            "Arbor Logistics",
            "Process Engineer Intern",
        ),
        app(
            "h-sr-conf-2",
            "smartrecruiters",
            [
                m(
                    "Cedar Point Labs",
                    "no-reply@smartrecruiters.com",
                    "Thank you for your application to Cedar Point Labs",
                    "Hello Sam,\n\nThank you for your interest in Cedar Point Labs! We have received your application for the Computational Chemistry Intern position and will be in touch if your background is a match.\n\nKind regards,\nCedar Point Labs Talent Acquisition",
                    13,
                )
            ],
            CONF,
            APPLIED,
            "Cedar Point Labs",
            "Computational Chemistry Intern",
        ),
    ]


def build_holdout() -> list[Case]:
    cases = [
        *_workday(),
        *_icims_sf_taleo(),
        *_gh_lever_ashby(),
        *_sr_workable_boards(),
        *_direct_recruiter_cal(),
        *_threads(),
        *_recruiters(),
        *_more(),
        *_noise(),
    ]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases
