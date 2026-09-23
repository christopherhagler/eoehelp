## 1. Who is responsible

eoehelp is run by one person, not a company. Christopher Hagler operates it as
an individual in Alabama, United States, at [POSTAL ADDRESS]. eoehelp is not
yet running on deployed infrastructure: it runs on development machines and
holds no real patient records. Where the servers will be, who runs them, and
what contract governs them will be stated here before that changes.

- Privacy questions and requests: [privacy@eoehelp.org](mailto:privacy@eoehelp.org)
- Security reports: [security@eoehelp.org](mailto:security@eoehelp.org)

Alabama has no comprehensive consumer privacy statute, so the rights described
in this policy come from Washington's and Nevada's consumer health data laws,
from federal law, and from choices made here. They are offered to everyone who
uses eoehelp, wherever they live.

HIPAA does not apply to eoehelp. HIPAA covers health care providers, health
plans, and the companies working for them. eoehelp is none of those: it is a
record you keep for yourself. Consumer health data laws do apply, including
Washington's My Health My Data Act and Nevada's SB370, and the Federal Trade
Commission's Health Breach Notification Rule applies to a service like this one.
The separate
[Consumer Health Data Privacy Policy](/health-data) states these same practices
in the form Washington law requires.

## 2. What this policy covers

This policy covers the eoehelp website and the eoehelp app. It describes what is
collected, why, who else ever receives anything, how long it is kept, and what
you can ask for.

## 3. What is collected, and why

Everything here is either something you typed or something the service needs to
work. There is no third-party source: nothing about you is bought, imported, or
inferred from anywhere else.

Table: What eoehelp stores

| Category | What it is | Why |
|---|---|---|
| Account | Your email address, the times you signed in, and sign-in and session tokens stored only as hashes | To let you in, and to let you back in on your own devices |
| Profile | A display name if you give one, your year of birth, sex at birth if you give it, the month of your diagnosis if you give it, and your timezone | We ask for the year of birth and use it to keep eoehelp to adults; the timezone decides which calendar day an entry belongs to, which changes what your record says |
| Health entries | Your daily symptom answers, foods and ingredients, medications and doses, endoscopy, biopsy and dilation details, and any notes you write | This is the record. It exists so you can keep it and show it to your clinician |
| Consent records | Which document version you agreed to, when, your IP address, your browser's user agent string, and a digest of the exact text | This is the evidence that you were asked and agreed, which is the point of asking |
| Activity log | Which records were read or changed, when, from which address, with your browser's user agent string, and details of the change | So that "was my record accessed" has an answer. It records field names and counts, never the values in them |
| Technical logs | The request method, the route pattern rather than the address you visited, the response status, how long it took, and a request id | To find and fix faults |

Your year of birth is stored instead of your full date of birth on purpose. A
full date of birth is one of the strongest identifiers there is, and the year is
all the age check needs.

## 4. What is never collected

- No full date of birth, home address, phone number, or payment details.
- No GPS or device location. eoehelp does not ask for it and does not use it.
  Your IP address is recorded as described in section 3.
- No advertising identifiers, and no device fingerprinting.
- No analytics, no advertising, and no tracking code anywhere in the app. The
  one third-party request any page makes is for the fonts, described below.
- No cookies except one. `eoehelp_refresh` keeps you signed in. It is httpOnly,
  Secure, restricted to this site, and scoped to the sign-in routes only. It is
  strictly necessary for the service to work, which is why there is no cookie
  banner: there is nothing optional to ask about.
- Your camera is used only while you are scanning a barcode, and only if you
  allow it. Your browser reads the barcode on your device. No image and no video
  leaves your device: only the decoded number is sent, so a product can be
  looked up.

## 5. Who else receives anything

The list is short. Apart from the company that will run the servers, nobody on
it receives your health entries.

Table: Everyone outside eoehelp who receives anything

| Who | What they receive | Why |
|---|---|---|
| A hosting provider, once there is one | Everything, as the operator of the servers and database | The service has to run somewhere. None is in use yet |
| The sign-in email sender | Your email address and the sign-in link | To send you the link you asked for |
| Open Food Facts and USDA FoodData Central | A product name you searched for, or a barcode you scanned, sent from our server | To look up the ingredients printed on a packaged food |
| Google Fonts | Your IP address, your browser's user agent, and the address of this site | The site loads font stylesheets and font files from Google. See below |

A word on each of the last two, because they are the ones that deserve
explaining.

- **Food lookups are made by our server, never by your browser.** Open Food
  Facts and USDA receive the search text or the barcode and nothing else: no
  account, no identifier, nothing that says who asked. They cannot connect a
  lookup to you.
- **Google Fonts is a request your browser makes.** Because it happens in your
  browser, Google sees your IP address and which site you are on. It does not
  see which page you are on, because this site sends a referrer policy that
  withholds it, and it receives nothing you typed. This is a dependency we
  intend to remove by serving the fonts ourselves.

Nothing is sold. Nothing goes to a data broker, an insurer, an employer, or an
advertiser. There is no analytics provider. If that ever changes, it would be a
new version of this policy and you would be asked again.

One more way information can leave:

- The law can require disclosure. If a valid legal demand arrives, you will be
  told unless the law forbids it.

There is no way to share your record from inside eoehelp today.

## 6. How it is protected

- Traffic is encrypted in transit.
- Data will be encrypted at rest by the hosting provider. No hosting provider
  is in use yet, so this is a commitment rather than a configuration.
- Free-text notes are encrypted a second time by the application itself, with a
  key kept outside the database, so a copy of the database alone does not
  reveal them.
- Every table holding your health entries is protected by database row-level
  security bound to your account. A query that does not name a patient returns
  nothing at all, by policy rather than by convention. The activity log is
  separate: the application can add to it and can never change or delete it.
- Sign-in links and session tokens are stored only as hashes, so a copy of the
  database cannot be used to sign in as you.
- The operator can reach the database to run and repair the service. Access
  through the application is recorded in the activity log.

No system is perfectly secure, and anyone who tells you otherwise is selling
something. What is claimed here is the design, not a guarantee of outcome.

## 7. How long it is kept

Your record is kept until you delete it or ask for it to be deleted. There is no
automatic expiry: a health record that quietly deletes itself after a year would
be worse than useless.

When an account is deleted, the account, the profile, and every clinical entry
are removed from the live database immediately. Two things survive on purpose:

- **The activity log.** It keeps the record of accesses and changes, including
  the deletion itself, with field names and never values. "Was this record
  accessed before it was erased" is the question a breach investigation asks,
  and an audit trail that can be erased by the person under investigation is not
  an audit trail.
- **Encrypted backups**, once eoehelp runs on deployed infrastructure. Backups
  exist so that a failure does not lose your record; the cost is that deleted
  data persists in them until they expire. The retention period will be stated
  here, and set so that it meets the deletion deadline the law requires.

## 8. Your choices

- **See and correct.** Everything you entered is visible in the app, and you can
  change it there.
- **Get a copy.** Email [privacy@eoehelp.org](mailto:privacy@eoehelp.org) from
  your account address and you will be sent a copy of your record. A screen for
  this is planned; today it is done by email.
- **Delete.** Email [privacy@eoehelp.org](mailto:privacy@eoehelp.org) from your
  account address and your account and record are deleted. It is real deletion,
  not a flag. A screen for doing it yourself is being built; until it exists,
  email is the way.
- **Research.** Sharing your record for research is not available yet. Nothing
  is shared with any researcher today. If it becomes available it will be opt-in,
  it will let you choose which categories to include, and you will be able to
  withdraw.

You will not be treated differently for exercising any of these.

## 9. If there is a breach

If your information is involved in a breach, you will be told without
unreasonable delay, along with what happened, what was involved, and what to do
about it. Three sets of rules apply, and the strictest of them governs:

- **The Alabama Data Breach Notification Act of 2018**, because the operator is
  in Alabama. It treats medical history, condition, treatment, and diagnosis as
  sensitive information, requires notice within 45 days of determining that a
  breach is reasonably likely to cause substantial harm, and requires notice to
  the Alabama Attorney General when more than 1,000 residents are affected.
- **The breach notification law of the state where you live**, which may be
  stricter.
- **The Federal Trade Commission's Health Breach Notification Rule**, which
  covers a health service like this one that is not a HIPAA covered entity.

## 10. Children

eoehelp is for people aged 18 and over. It is not directed to children, and no
account may be created for one. An account found to belong to someone under 18
will be deleted. Eosinophilic esophagitis affects many children, and a product
for them needs parental consent handled properly. That is a deliberate later
piece of work, not an oversight.

## 11. Where eoehelp is offered

eoehelp is offered to people in the United States. It is not directed to people
in the European Union or the United Kingdom, and it is not built to meet those
regimes.

## 12. Changes to this policy

A change means a new version of this document with its own id. You will be asked
to agree again rather than being treated as having agreed by carrying on using
the service. Every version you agreed to stays readable at its own address, and
your consent record names the version and pins its exact text.

## 13. Contact and complaints

Write to [privacy@eoehelp.org](mailto:privacy@eoehelp.org) with any question or
request about your information, or to
[security@eoehelp.org](mailto:security@eoehelp.org) to report a security
problem. Postal mail reaches the operator at [POSTAL ADDRESS].

If you live in Washington, you may also complain to the Washington State
Attorney General.
