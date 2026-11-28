"""The in-app manual (Help, /help): how to do things in QuoteRoom, step by step, with a search box.

Each article: id, title, what it's for (summary), words people might search with (tags), steps, the page it's on
(link: an endpoint), admin (only admins can do it: hidden from employees) and needs (a feature that's off unless
turned on: hidden where it's off). Searching works on the page itself (no AI); "Ask" sends the question and this
manual to the AI (app/help_bp.py), which answers only from it.

Keep it in step with the app: when a feature or a button's name changes, change its article here.
"""

ARTICLES = [
    # ── Quotations ──────────────────────────────────────────────────────────
    dict(id='new-quote', title='Make a new quotation', link='projects.create_project',
         summary='Customer details, rooms (or sections) and their lines, then save.',
         tags='create add new quote estimate start first quotation customer rooms items',
         steps=['Tap New Quote in the menu.',
                'Type the customer\'s name and mobile number (email and address are optional).',
                'Under Rooms & Items, name the first room (e.g. Kitchen) and add its lines: tap an item, type the size or quantity.',
                'Add more rooms with Add Another Room at the bottom (Section or Area, depending on your work).',
                'Check the total on the right (or at the bottom on a phone), add a discount if any.',
                'Tap Save Quotation. It opens the quotation, ready to send.']),
    dict(id='edit-quote', title='Change a quotation', link='projects.list_projects',
         summary='Open it, tap Edit, change, save: it becomes the next revision.',
         tags='edit change modify update revise correct quotation revision',
         steps=['Open Quotations and tap the customer.',
                'Tap Edit.',
                'Change sizes, lines, rates or the discount.',
                'Tap Update Quotation. The change is kept as a new revision: the first version is Rev 0 (its number shows without /Rev), the first change Rev 1, then Rev 2…, and the older ones stay under Revisions.']),
    dict(id='duplicate', title='Copy a quotation for another customer', link='projects.list_projects',
         summary='Duplicate starts a new quotation with all the same rooms and lines.',
         tags='duplicate copy clone same similar reuse another customer',
         steps=['Open the quotation you want to copy.',
                'Tap Duplicate.',
                'Type the new customer\'s name and mobile, change what\'s different, and save.']),
    dict(id='templates', title='Save and use quotation templates', link='projects.manage_templates', admin=True,
         summary='Keep a ready-made quotation (e.g. 2 BHK) to start new ones from.',
         tags='template templates package standard 2bhk 3bhk ready made starting saved preset clone copy duplicate new create',
         steps=['Open a quotation that\'s a good starting point.',
                'Tap Save as template and give it a name (e.g. 2 BHK turnkey).',
                'Next time, on New Quote, pick the template: its rooms and lines are filled in; type the sizes and the customer.',
                'Admin → Templates lists them: Edit lines changes one, Clone copies one under a new name (change what differs, '
                'e.g. a premium version), New template starts an empty one you fill in, and you can rename or delete them.']),
    dict(id='draft', title='Find a half-filled quotation (drafts)', link='projects.list_projects',
         summary='Quotations are saved as drafts while you type.',
         tags='draft autosave lost unsaved half filled incomplete phone locked',
         steps=['Open Quotations: drafts are marked Draft.',
                'Tap it to carry on, then save it to make it a quotation.']),
    dict(id='search-quotes', title='Find a quotation', link='projects.list_projects',
         summary='Search by customer name, mobile or quotation number.',
         tags='search find look up customer mobile number quotation number filter list',
         steps=['Open Quotations.',
                'Type the customer\'s name, mobile or the quotation number in the search box.']),
    dict(id='delete-quote', title='Delete a quotation', link='projects.list_projects', admin=True,
         summary='Admins only; it can\'t be undone.',
         tags='delete remove quotation trash',
         steps=['Open the quotation.', 'Tap Delete and confirm. Only admins can delete; it can\'t be brought back.']),
    dict(id='discount', title='Give a discount', link='projects.create_project',
         summary='A percentage or a fixed amount on the whole quotation.',
         tags='discount less reduce offer percentage fixed amount off',
         steps=['On the quotation form, find Discount (with the total).',
                'Choose Percentage or Fixed and type the amount.',
                'Save. The PDF shows the total, the discount and the final amount.']),
    dict(id='nos', title='No\'s: identical pieces on a line', link='projects.create_project',
         summary='Two identical shutters on one line: No\'s 2 multiplies the area.',
         tags="nos no's number pieces count quantity identical multiply",
         steps=['On a line with a size, type the number in No\'s (e.g. 2).',
                'The area (and the amount) is multiplied by it.',
                'Priced per sqft and want No\'s to multiply the rate instead (e.g. 1.25 for extra work)? See "No\'s multiplies the rate".']),
    dict(id='nos-rate', title='No\'s multiplies the rate, not the area', link='admin.settings', admin=True, tab='pricing',
         summary='On sqft lines, No\'s becomes a factor on the rate (1.25); the measurement stays as measured.',
         tags="nos no's factor rate multiply extra work 1.25 decimal sqft area measurement",
         steps=['Open Admin → Settings → Pricing.',
                'Turn on "No\'s multiplies the rate, not the area" and save.',
                'On a sqft line, No\'s 1.25 at ₹120 prints as the measured area at ₹150; No\'s isn\'t printed. Running ft, Nos and lump sums don\'t change.',
                'On the quotation form, the size line shows the calculated area after "=" (measured × No\'s, what the amount is on), '
                'with the measured area the PDF shows.']),
    dict(id='hide-rates', title='Hide rates while quoting in front of the customer', link='admin.settings', admin=True, tab='pricing',
         summary='Rates and each line\'s amount are hidden on the form and quotation page (for everyone), with a Show rates button.',
         tags='hide rates screen customer watching show rates privacy',
         steps=['Open Admin → Settings → Pricing.',
                'Turn on "Hide rates while making quotations" and save.',
                'Rates and line amounts are hidden on screen; room totals and the grand total still show. Tap Show rates on the page when you need them. The PDF is unchanged.']),
    dict(id='stages', title='Move a job through its stages', link='projects.list_projects',
         summary='Awaiting confirmation → Confirmed → Ongoing → Completed (or On hold, Cancelled).',
         tags='stage status confirmed ongoing completed cancelled on hold pipeline progress',
         steps=['Open the quotation.', 'Tap the stage next to the customer\'s name and pick the new one (add a note if you like).',
                'A customer accepting online moves it to Confirmed by itself.']),
    dict(id='revisions', title='See or restore an older version', link='projects.list_projects',
         summary='Every saved change is a revision; you can open or restore any of them.',
         tags='revision version history older previous restore undo rev changes',
         steps=['Open the quotation and scroll to Revisions.',
                'Open a revision to see its PDF and what changed.',
                'Admins can tap Restore revision to make it the current one again (saved as a new revision).']),
    dict(id='quote-numbers', title='Choose how quotation numbers look', link='admin.settings', admin=True, tab='documents',
         summary='Date + count (2026111901), a running number (QT-001), financial year (QT/2026-27/001) or your own.',
         tags='quotation number numbering sequence format series prefix serial running',
         steps=['Open Admin → Settings → Quotation PDFs → Quotation numbers.',
                'Tap a ready format, or type your own with {YYYY} {MM} {DD} {FY} and the count {NNN}.',
                'To carry on your old series, type the number in "Start the count from".',
                'Save. All quotations are numbered again in the new format, in the order they were made.']),

    # ── Sending ─────────────────────────────────────────────────────────────
    dict(id='pdf', title='Get the quotation PDF', link='projects.list_projects',
         summary='Tap the PDF button on the quotation, or beside it in your Quotations list.',
         tags='pdf download print save share file quotation pdf initial full number quotation no revision',
         steps=['Open the quotation.',
                'Tap Quotation PDF (or Full Quotation / Initial Quotation, depending on how you price).',
                'It opens in a new tab: download, print or share it from there. The PDF button in the Quotations list opens it the same way.',
                'It prints the quotation\'s number with its revision beside the date (Quotation No: QT-016 for the first version, QT-016/Rev1 after the first change…), as on your Quotations page. To leave it off, untick "Print the number on the quotation PDF" in Admin → Settings → Quotation PDFs → Quotation numbers.']),
    dict(id='pdf-choices', title='Choose what the PDF shows', link='projects.list_projects', needs='pdf_choices',
         summary='Tick-boxes before the PDF: description, material, size, quantity, rate, amounts, room totals, photos.',
         tags='pdf choose show hide columns rate amount size description tick boxes customer sees',
         steps=['Open the quotation and tap the PDF button.',
                'Tick what the customer should see, untick the rest.',
                'Tap Open PDF. The customer\'s link and emailed PDF show the same; the choice is kept for that quotation.']),
    dict(id='whatsapp', title='Send the quotation on WhatsApp', link='projects.list_projects',
         summary='A ready message with the summary, totals and payment details, or the approval link.',
         tags='whatsapp send share message customer phone',
         steps=['Open the quotation.',
                'Create the approval link (Online approval) and tap Send link on WhatsApp, or send the PDF from the PDF viewer.',
                'WhatsApp opens with the message ready: check it and send.']),
    dict(id='approval-link', title='Let the customer accept online', link='projects.list_projects',
         summary='A private link where the customer sees the quotation, downloads it and taps Accept or Request changes.',
         tags='link online approval accept customer approve request changes share url',
         steps=['Open the quotation and find Online approval.',
                'Tap Create approval link (choose what it shows), then Send link on WhatsApp.',
                'When the customer accepts, the job moves to Confirmed and you get a notification. You can see when they opened it.']),
    dict(id='email-quote', title='Email the quotation', link='projects.list_projects',
         summary='Sent from your own email account with the PDF attached.',
         tags='email mail send quotation attach gmail',
         steps=['Set up email once: Admin → Settings → Email (an admin does this).',
                'Open the quotation and tap Email.',
                'Check the address, choose the PDF and send.']),
    dict(id='email-setup', title='Set up email sending', link='admin.settings', admin=True, tab='email',
         summary='Your email account, so quotations, invoices and receipts go from your address.',
         tags='email smtp gmail setup app password mail server',
         steps=['Open Admin → Settings → Email.',
                'Fill in your email server details (for Gmail: an app password).',
                'Save and tap Send test email to check.']),
    dict(id='validity', title='Show "Valid until" on quotations', link='admin.settings', admin=True, tab='documents',
         summary='A number of days from the quotation\'s date.',
         tags='validity valid until expiry days expire date',
         steps=['Open Admin → Settings → Quotation PDFs → Validity.',
                'Type the number of days (e.g. 30) and save. Leave it empty to not show it.']),
    dict(id='pdf-sections', title='Payment terms, notes and terms & conditions on the PDF', link='admin.settings', admin=True, tab='documents',
         summary='Material Specifications, Payment Terms, Delivery Terms, Important Notes and Terms & Conditions.',
         tags='terms conditions payment terms delivery notes specifications warranty pdf text sections placeholder insert board option variable',
         steps=['Open Admin → Settings → Quotation PDFs.',
                'Type in each section (bold, lists and tables print as you see them). Leave one empty to leave it out.',
                'Use Insert to add details that change per quotation, like {customer} or {plywood_details}. Each item options section (Admin → Rates) has its own button too: {Board} prints the board(s) chosen on that quotation, e.g. "{Board} for all carcass units" → "16mm Century Bond 710 for all carcass units". Priced by item, the Plywood and Materials used buttons aren\'t shown (those come from pricing by material).',
                'Save. Every quotation PDF prints them at the end.']),
    dict(id='page-breaks', title='Page breaks in the PDF', link='admin.settings', admin=True, tab='documents',
         summary='Start a section (e.g. Terms & Conditions) on a new page, or let them follow on with no gap.',
         tags='page break new page blank space gap pdf layout section',
         steps=['Open Admin → Settings → Quotation PDFs.',
                'On each section, tick "Start on a new page in the PDF" for the ones that should begin on a fresh page.',
                'Save. The others follow straight on, with no gap.']),
    dict(id='pdf-look', title='Change how the PDF looks', link='admin.settings', admin=True, tab='documents',
         summary='Colours, font, header, page border, logo watermark, cover page, presentation pages, room descriptions.',
         tags='pdf look design colour layout cover page header style watermark logo border frame line outline rounded double',
         steps=['Open Admin → Settings → Quotation PDFs.',
                'Change How your PDF looks (and the cover page, if you have it).',
                'Page border: pick no border, a thin, thick or double line, or rounded corners (in your brand colour), and whether it goes on the front page only or on every page of your quotation PDFs.',
                'Turn on Your logo as a watermark to put your logo, faint, in the middle of every page of your quotation PDFs (not the title, About us and Next steps pages). '
                'An employee\'s quotation gets it once you approve it.',
                'Save and open a quotation PDF to see it.']),
    dict(id='tick-several', title='Add several items to a room at once', link='projects.create_project', needs='tick_several',
         summary='Tick several lists your items, fittings and lump sums A–Z: tick what goes in the room and add them together.',
         tags='tick several many multiple items add at once bulk select fittings lump sum list alphabetical',
         steps=['On the quotation form, tap Tick several under the room.',
                'Pick the material & work at the top (for the plain item names), or search.',
                'Tick the items, fittings and lump sums for this room (Tick all ticks a whole group). Everything is listed A–Z.',
                'Tap Add: they come into the room in that order. Type each item\'s size (highlighted until you do); fittings come in with quantity 1 at your price.',
                'Move any line with the up and down arrows beside it.']),
    dict(id='add-my-lines', title='Add several of your saved lines to a room', link='projects.create_project', needs='boq_lines',
         summary='Add from my lines: tick your saved lines and add them at once, then type each quantity.',
         tags='add from my lines saved lines several many multiple at once bulk boq select',
         steps=['On the quotation form, tap Add from my lines under the room.',
                'Search or tick the lines you need (Tick all ticks a whole group); the group named like the room is on top.',
                'Tap Add lines, then type each line\'s size or quantity (highlighted until you do).',
                'Move any line with the up and down arrows beside it.']),
    dict(id='box-frame-lines', title='Two rates for one item (Box Work and Frame Work)', link='admin.rates', needs='boq_lines',
         summary='Save the item twice, ending its name in " – Box Work" and " – Frame Work": each has its own rate, the customer sees the item\'s name alone.',
         tags='box work frame work two rates same item carcass shutter only name ending hidden customer',
         steps=['In Admin → Rates, save the item twice with its two rates, e.g. "Kitchen Base Unit – Box Work" at ₹2,200 and "Kitchen Base Unit – Frame Work" at ₹1,000.',
                'On a quotation, pick the one you mean: the form shows the full name.',
                'The PDF, the customer\'s link, WhatsApp and invoices print "Kitchen Base Unit" (with Settings → Quotation PDFs showing work types to customers, the full name).']),
    dict(id='item-options', title='Item options: finish, board, brand… (one choice from each section)', link='admin.rates', needs='boq_lines',
         summary='The same item at another finish or board: sections of your own (Finish, Board…), each option adding a % or ₹ per unit to the rate.',
         tags='item options per quotation default whole quotation finish finishes board plywood brand grade acrylic laminate century bond sainik gurjan upgrade extra percent rupees per sqft section choice',
         steps=['In Admin → Rates → Item options, tap Add section, name it (e.g. Board) and list its options (Add option for more). The first is your base: your items\' rates are for it.',
                'Give each other option its extra: a % of the base rate (Acrylic +25%) or ₹ per unit (Century Bond +₹400 per sqft). A cheaper one can take off (−100).',
                'Add section again for another (e.g. Finish, then Board). Each section gets a tick column in Your items & rates: tick the items that come in it.',
                'On a quotation, those items show one choice per section; picking one changes the rate by itself (₹1,800 → Acrylic +25% → Century Bond +₹400 = ₹2,650).',
                'To pick a section once for the whole quotation (e.g. this home is on Century Bond), tick Choose per quotation on it. The quotation form then has Item options for this quotation at the top: new lines start on that choice, and changing it moves every line still on the old one. A line changed on its own keeps its choice.',
                'Base options aren\'t printed; others are, after the item\'s name: "Wardrobe (Acrylic finish, Century Bond)". A business already set up with Finishes keeps them as a section named Finish.',
                'To name the choice in your Material Specifications, use Insert → the section\'s name (e.g. {Board}) in Settings → Quotation PDFs: each PDF prints the option(s) its items are on.']),
    dict(id='line-order', title='Change the order of lines in a room', link='projects.create_project',
         summary='The arrows beside each line move it up or down.',
         tags='order move up down reorder arrange sort lines items room sequence',
         steps=['On the quotation form, find the line in its room.',
                'Tap the up or down arrow beside its remove (×) button to move it.',
                'Save: the quotation, PDF and customer\'s link show the lines in that order.']),
    dict(id='new-bom', title='Measure a home first: New Carpet Area', link='boms.list_boms', needs='boms',
         summary='Room-wise measurements (length × width, area, total), saved on their own before you quote.',
         tags='carpet area bom bill of measurements measurement measure room areas sizes length width sqft sq m total site visit new bom',
         steps=['Tap Carpet Areas at the top, then New Carpet Area.',
                'Type the customer\'s name and mobile (email and address are optional).',
                'Add each area: its name, length and width, in your own unit. Each area and the total are worked out.',
                'Save. The Carpet Areas page lists every carpet area; open one to edit it or make quotations from it.',
                'The measurements are for you and your team only. A quotation made from the carpet area shows just the total as Carpet area '
                'in the customer details on the first page of its PDF.']),
    dict(id='bom-quote', title='Make a quotation from a carpet area (basic and premium)', link='boms.list_boms', needs='boms',
         summary='Create quotation on a carpet area: its customer, and the areas you tick as rooms.',
         tags='carpet area bom quotation from measurements create quotation basic premium options rooms tick',
         steps=['Open the carpet area and find Create quotation.',
                'Tick the areas that become rooms (a passage with no work can stay unticked).',
                'Optionally pick a starting quotation; its rooms and lines come too.',
                'Tap Create quotation: the customer and rooms are filled in, and the measurements show for reference. Add the items and save.',
                'Do it again for another option (premium): every quotation made from the carpet area is listed on it.']),
    dict(id='bom-settings', title='Turn on Carpet Area, and who can use it', link='admin.settings', admin=True, tab='pricing',
         summary='Settings → Pricing → Carpet Area; staff use it too unless you turn that off.',
         tags='carpet area bom boms settings staff employees access turn on off measurements',
         steps=['Open Settings → Pricing → Carpet Area and turn on Carpet Area.',
                'Staff can use Carpet Area is on by default: everyone sees every carpet area and makes quotations from them. Turn it off for admins only.',
                'Save.']),
    dict(id='photos', title='Add photos to a quotation', link='projects.list_projects', needs='photo_pages',
         summary='A cover photo and gallery pages in the PDF and on the customer\'s link.',
         tags='photos images pictures gallery cover design render',
         steps=['Open the quotation and tap Add photos.', 'Choose the photos; tick which print.', 'They show on the PDF and link.']),

    # ── Rates & pricing ─────────────────────────────────────────────────────
    dict(id='rates', title='Change your rates', link='admin.rates', admin=True,
         summary='Your items, materials, fittings and lines with their rates.',
         tags='rates price list change rate update sqft material item cost per',
         steps=['Open Admin → Rates.',
                'Change a rate and save. New quotations use it; saved quotations keep their prices until edited.']),
    dict(id='add-line', title='Add a new item or line to your rates', link='admin.rates', admin=True,
         summary='Add it once to Rates, or type a new one on a quotation and keep it.',
         tags='add new item line rate save default my lines price list',
         steps=['Open Admin → Rates and add the line with its rate and description, picking its unit (sqft, sqm, rft, rmt, no\'s, lump sum, or one of your own: Edit beside Unit adds or removes them), or',
                'on a quotation, type a new line and tick to keep it for next time.']),
    dict(id='remove-line', title='Remove items you don\'t use from Rates', link='admin.rates', admin=True,
         summary='Delete lines you never quote.',
         tags='remove delete default starter items lines rates clean',
         steps=['Open Admin → Rates.', 'Delete the lines you don\'t use (the delete button on each). Saved quotations aren\'t changed.']),
    dict(id='pricing-mode', title='Price by item or by material', link='admin.settings', admin=True, tab='pricing',
         summary='By item: each line has its own rate. By material: a rate per sqft for each material and work type.',
         tags='pricing by item by material mode how price boq turnkey',
         steps=['Open Admin → Settings → Pricing.', 'Choose how you price your work and save.']),
    dict(id='plywood', title='Plywood (boards) and their prices', link='admin.rates', admin=True,
         summary='Your board list with a price difference per sqft from your default.',
         tags='plywood board ply bwp mr marine pvc wpc thickness grade brand',
         steps=['Open Admin → Rates → Board (plywood, PVC, WPC).',
                'Add your boards and the difference from your default (e.g. +150 per sqft).',
                'On a quotation, pick the board: everything on it re-prices.']),
    dict(id='units', title='Measure in mm, cm, inches or feet', link='admin.settings', admin=True, tab='units',
         summary='Sizes and areas in your unit for the whole team.',
         tags='units mm cm inches feet metre sq m sqft measurement unit',
         steps=['Open Admin → Settings → Units.', 'Choose the size unit and the area unit, and save. Nothing already saved changes.']),
    dict(id='costs', title='See profit on each quotation', link='admin.costs', admin=True,
         summary='Type what things cost you; each quotation shows its profit. Never shown to staff or customers.',
         tags='profit margin cost price purchase costs earnings items item options board finish extra cost',
         steps=['Open Admin → Costs & Profit.', 'Type your costs and save.',
                'Priced by item: type what each of your items costs you per unit (on your base options). For item options (Board, Finish…), type what each other option costs you extra, or leave it empty to use its price extra.',
                'Each quotation shows its estimated profit and margin, with each line\'s options counted.']),
    dict(id='import-old', title='Bring in an old quotation or rate list', link='admin.ai_import', admin=True, needs='ai_import',
         summary='Upload a PDF or Excel: its lines and rates are read for you to check.',
         tags='import upload excel pdf old quotation rate list ai read',
         steps=['Open Admin → Import a quotation.', 'Upload the file.', 'Check what was read and save.']),

    # ── Team ────────────────────────────────────────────────────────────────
    dict(id='add-user', title='Add a team member', link='admin.users', admin=True,
         summary='Staff logins, as employee or admin.',
         tags='user staff employee team login add member account password',
         steps=['Open Admin → Users and tap Add User.', 'Fill in the username, password and role (employee or admin), and save.',
                'Share the login with them. Employees see only the quotations they\'re given.']),
    dict(id='access', title='Give an employee a quotation', link='projects.list_projects', admin=True,
         summary='Can view or Can edit, per quotation.',
         tags='access share employee permission view edit give assign',
         steps=['Open Quotations and tap the Access button (people icon) on the quotation.', 'Choose Can view or Can edit for each employee, and save.']),
    dict(id='employee-rates', title='Let an employee see rates', link='admin.users', admin=True,
         summary='Employees don\'t see rates or line amounts unless you allow it.',
         tags='employee rates hidden see rates allow permission amounts',
         steps=['Open Admin → Users and tick Can see rates for that employee (every quotation), or',
                'when an employee asks for one quotation\'s rates, tap Approve on the notification.']),
    dict(id='ask-rates', title='Ask your admin to see the rates', link='projects.list_projects',
         summary='For employees: rates are hidden until the admin allows them.',
         tags='ask rates employee hidden see amounts request',
         steps=['Open the quotation.', 'Tap Ask admin for rates.', 'Once your admin approves, that quotation shows its rates.']),
    dict(id='approvals', title='Approve employees\' quotations', link='admin.notifications', admin=True, needs='approvals',
         summary='Employees can look at their quotation\'s PDF (marked Draft), but download and share it only after an admin approves it.',
         tags='approve approval reject changes employee quotation review check notification draft',
         steps=['When an employee taps Send for approval you get a notification.',
                'On the notification (or the quotation), tap Approve, Make changes (with a note) or Reject.',
                'Once approved, the employee can download it and send it to the customer (WhatsApp, email, link).',
                'If they change it afterwards, it needs your approval again before it\'s shared.']),
    dict(id='send-approval', title='Send a quotation for approval (employees)', link='projects.list_projects', needs='approvals',
         summary='Make it and check the PDF yourself; tap Send for approval to download it and share it with the customer.',
         tags='approval send waiting approved locked cannot download share pdf draft employee',
         steps=['Make and save the quotation. Its PDF opens for you to check, marked Draft – not approved.',
                'When it\'s ready, tap Send for approval on the quotation.',
                'Its page says Waiting for approval. If the admin asked for changes, make them and tap Send for approval again.',
                'Once approved, you can download the PDF and share it: link, WhatsApp and email.']),

    # ── Payments & invoices ─────────────────────────────────────────────────
    dict(id='record-payment', title='Record a payment', link='projects.list_projects',
         summary='Advances and instalments, with the balance worked out.',
         tags='payment record received advance instalment paid balance cash',
         steps=['Open the quotation and tap Record Payment.', 'Type the amount, date and how it was paid, and save. The balance updates.']),
    dict(id='payment-link', title='Send a payment link', link='projects.list_projects',
         summary='A Razorpay link for the balance or part of it; paid links are recorded by themselves.',
         tags='payment link razorpay upi card pay online collect',
         steps=['Set up Razorpay once: Admin → Payment Settings (an admin does this).',
                'Open the quotation, choose the amount and create the payment link.', 'Send it on WhatsApp.']),
    dict(id='payment-settings', title='Payment details (UPI, bank) on PDFs', link='admin.payment_settings', admin=True,
         summary='Your UPI ID and bank account print on every PDF.',
         tags='upi bank account ifsc payment details razorpay settings',
         steps=['Open Admin → Payment Settings.', 'Type your UPI ID and bank details (and Razorpay keys for links) and save.']),
    dict(id='reminder', title='Remind a customer to pay', link='billing.balances_due',
         summary='A polite WhatsApp reminder with the amount due and your payment details.',
         tags='reminder remind payment due balance owe collect follow up',
         steps=['Open Balances (or the quotation\'s Payments).', 'Tap Remind / Send on WhatsApp, check the message and send.']),
    dict(id='balances', title='See who still owes money', link='billing.balances_due',
         summary='Every customer with a balance, biggest first.',
         tags='balances due owe pending outstanding money collect',
         steps=['Open Balances in the menu.']),
    dict(id='invoice', title='Make an invoice', link='projects.list_projects',
         summary='From a confirmed quotation, with or without GST.',
         tags='invoice bill gst tax invoice cgst sgst igst billing delete remove cancel mistake',
         steps=['Open the quotation.', 'Tap Create invoice, check the details (GST or not) and tap Issue invoice.',
                'Send it as a PDF, link, WhatsApp or email.',
                'Made one by mistake? Admins can tap Cancel (it stays on record, marked cancelled; its number isn\'t reused) or the bin to delete it for good (its link stops working; deleting the latest one frees its number). Once an invoice has gone to the customer or into your GST returns, cancel it rather than delete it.']),
    dict(id='invoice-settings', title='Invoice settings (GST, numbering)', link='admin.settings', admin=True, tab='invoices',
         summary='Your GSTIN, HSN/SAC and how invoices are numbered.',
         tags='invoice settings gst gstin hsn sac number prefix',
         steps=['Open Admin → Settings → Invoices.', 'Fill in your GST details and save.']),

    # ── Your business ───────────────────────────────────────────────────────
    dict(id='company', title='Company name, address, logo', link='admin.settings', admin=True, tab='company',
         summary='What prints on every PDF and page.',
         tags='company name address phone gstin logo business details',
         steps=['Open Admin → Settings → Company for name, address and phone.',
                'Open Settings → Appearance for the logo and colours.',
                'The company name, GSTIN and logo lock once saved: ask support to change them.']),
    dict(id='colours', title='Colours and look of the app', link='admin.settings', admin=True, tab='appearance',
         summary='Pick a theme or your own colours and fonts.',
         tags='colour color theme brand look font style appearance',
         steps=['Open Admin → Settings → Appearance.', 'Pick a preset or your own colours and save.']),
    dict(id='home-page', title='Open the Dashboard first after signing in', link='admin.settings', admin=True, tab='appearance',
         summary='Admins can land on the Dashboard instead of Quotations.',
         tags='home page dashboard start landing first page login open',
         steps=['Open Admin → Settings → Appearance → Home page.', 'Choose Dashboard and save.']),
    dict(id='dashboard', title='Dashboard and reports', link='admin.dashboard', admin=True,
         summary='Work at each stage; reports by financial year.',
         tags='dashboard reports sales collected summary year month figures',
         steps=['Open Admin → Dashboard for work at each stage.', 'Open Admin → Reports for the year\'s sales, collections, GST and profit.']),
    dict(id='notifications', title='Notifications', link='admin.notifications', admin=True,
         summary='Payments received, customers\' replies and requests from your team.',
         tags='notifications bell alerts messages requests',
         steps=['Tap the bell.', 'Requests (rates, approvals) have their buttons right there.']),
    dict(id='material-list', title='Material list for a job', link='projects.list_projects', needs='material_list',
         summary='Everything to buy for the job, grouped, to copy or WhatsApp to suppliers.',
         tags='material list purchase buy order supplier sheets hardware',
         steps=['Open the quotation and tap the material list button.', 'Tick or change what\'s needed.', 'Copy or WhatsApp each group to its supplier.']),
    dict(id='ai-draft', title='Draft a quotation from a WhatsApp message or notes (AI)', link='projects.create_project', needs='ai_draft',
         summary='Paste the customer\'s requirements: the quotation is filled in with your own items and rates.',
         tags='ai draft message whatsapp notes paste automatic photo site notes',
         steps=['Tap New Quote → Draft from a message or notes.', 'Paste the message (or add photos of notes).', 'Check the draft, fill in what\'s highlighted, save.']),
    dict(id='ai-check', title='Check a quotation before sending (AI)', link='projects.list_projects', needs='ai_check',
         summary='Missing sizes, odd rates, things such rooms usually need, spelling.',
         tags='check ai mistakes review before sending missing',
         steps=['Open the quotation.', 'Tap Check before sending.', 'Fix what it points out.']),
    dict(id='app-icon', title='Put the app on your phone\'s home screen', link='projects.list_projects',
         summary='One tap to open, with your logo; nothing to install.',
         tags='install app home screen phone icon shortcut android iphone',
         steps=['Open the app in Chrome (Android) or Safari (iPhone).',
                'Android: menu ⋮ → Add to Home screen. iPhone: Share → Add to Home Screen.']),
    dict(id='password', title='Change your password', link='projects.list_projects',
         summary='Admins set passwords on the Users page; a forgotten admin password can be reset by email.',
         tags='password change reset forgot login',
         steps=['Employees: ask your admin. They set a new one on Admin → Users (Change password on your row).',
                'Admins: on the sign-in page tap Forgot password: a reset link goes to the business email.']),
    dict(id='partner-program', title='Partner program: earn by recommending us', link='referrals.refer', admin=True, needs='refer',
         summary='Partners are selected, not open to all: apply, and once we approve you, share your code and earn a share of what businesses you refer pay.',
         tags='partner program refer earn referral partner commission code link share money payout friend recommend',
         steps=['Open Admin → Partner program and read how it works (it opens once you\'ve been on a paid plan for the months shown, or sooner if we\'ve invited you).',
                'Fill in the form: your name, number, city and business are filled in for you; add your UPI ID or bank account and PAN, and send it.',
                'We review it. You can start only once it\'s approved: the page then shows your code (like QR2345) and a sign-up link.',
                'Share the link or code (Share on WhatsApp). Businesses that sign up with it get a longer free trial; you earn only once they buy a paid plan, not for the trial.',
                'Your page shows who signed up, every payment they make and what it earns you, and your payouts. We pay at the end of each month once you\'re owed the minimum shown; less carries over.']),
    dict(id='support', title='Get help from us', link='admin.support', admin=True,
         summary='WhatsApp or email support, or book a call.',
         tags='support help contact call whatsapp problem',
         steps=['Open Admin → Support.']),
]


def flags():
    """Features that are on in this business ({needs: bool})."""
    out = {}
    try:
        from . import pdf_choices, approvals, photo_pages
        out.update(pdf_choices=pdf_choices.enabled(), approvals=approvals.enabled(), photo_pages=photo_pages.enabled())
    except Exception:
        pass
    try:
        from . import ai_tools
        out.update(ai_draft=ai_tools.switched_on('draft'), ai_check=ai_tools.switched_on('check'))
    except Exception:
        pass
    try:
        from . import ai_import
        out['ai_import'] = ai_import.available()
    except Exception:
        pass
    try:
        from . import referrals
        out['refer'] = referrals.available()
    except Exception:
        pass
    try:
        from . import material_list
        out['material_list'] = material_list.available()
    except Exception:
        pass
    try:
        from . import boms
        out['boms'] = boms.enabled() and boms.ready()
    except Exception:
        pass
    try:
        from . import boq
        lines = boq.enabled()
        out.update(boq_lines=lines, tick_several=not lines)   # BOQ lines: Add from my lines; else Tick several
    except Exception:
        pass
    return out


def for_user(user):
    """The articles this user can use, with their links: [{id, title, summary, tags, steps, url}]."""
    from flask import url_for
    on = flags()
    out = []
    for a in ARTICLES:
        if a.get('admin') and not getattr(user, 'is_admin', False):
            continue
        if a.get('needs') and not on.get(a['needs']):
            continue
        try:
            url = url_for(a['link'], **({'tab': a['tab']} if a.get('tab') else {})) if a.get('link') else ''
        except Exception:
            url = ''
        out.append({'id': a['id'], 'title': a['title'], 'summary': a['summary'], 'tags': a['tags'],
                    'steps': a['steps'], 'url': url})
    return out


def as_text(articles):
    """The manual as plain text, for the AI."""
    return '\n\n'.join(f"[{a['id']}] {a['title']}\n{a['summary']}\n" + '\n'.join(f'{i}. {s}' for i, s in enumerate(a['steps'], 1))
                       for a in articles)
