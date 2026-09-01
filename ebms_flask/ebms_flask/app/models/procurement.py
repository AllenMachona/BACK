from datetime import datetime
from app.extensions import db


class Procurement(db.Model):
    __tablename__ = 'procurements'

    id = db.Column(db.Integer, primary_key=True)
    tender_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(30), nullable=False)  # works, services, consultancy, supplies, combination
    procurement_entity = db.Column(db.String(200))
    ppra_code = db.Column(db.String(50))
    ppra_sub_code = db.Column(db.String(20))
    method = db.Column(db.String(30), nullable=False)  # open_domestic, open_international, restricted, rfq, direct, rfp...
    evaluation_method = db.Column(db.String(50))        # least_cost_services, least_cost_supplies, quality_based, quality_cost_based, least_cost_works
    envelope_type = db.Column(db.String(10), default='single')  # single, dual
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    user_department = db.Column(db.String(150))

    submission_deadline = db.Column(db.DateTime)
    clarification_deadline = db.Column(db.DateTime)
    opening_scheduled_at = db.Column(db.DateTime)

    # Status follows SOAR Appendix C's bid status lifecyle.
    status = db.Column(db.String(30), default='draft', index=True)

    cancelled = db.Column(db.Boolean, default=False)
    cancelled_reason = db.Column(db.Text)
    cancelled_at = db.Column(db.DateTime)
    replacement_of_id = db.Column(db.Integer, db.ForeignKey('procurements.id'))

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Tender Document Fee & Document Storage
    tender_fee = db.Column(db.Numeric(15, 2), default=0.00)

    # Requesting user/department internal forms
    form_d_file_path = db.Column(db.String(500))
    form_d_filename = db.Column(db.String(300))
    form_e_file_path = db.Column(db.String(500))
    form_e_filename = db.Column(db.String(300))

    # Bidder-facing tender documents (gated by payment verification)
    itt_file_path = db.Column(db.String(500))
    itt_filename = db.Column(db.String(300))
    # Bidder-facing document that is free to view (no payment required),
    # e.g. a Request for Quotation document.
    rfq_file_path = db.Column(db.String(500))
    rfq_filename = db.Column(db.String(300))

    # Relationships
    lots = db.relationship('Lot', backref='procurement', lazy='dynamic', cascade='all, delete-orphan')
    submissions = db.relationship('Submission', backref='procurement', lazy='dynamic')
    criteria = db.relationship('EvaluationCriteria', backref='procurement', lazy='dynamic')
    evaluations = db.relationship('Evaluation', backref='procurement', lazy='dynamic')
    committee_members = db.relationship('CommitteeMember', backref='procurement', lazy='dynamic')
    communications = db.relationship('Communication', backref='procurement', lazy='dynamic')
    complaints = db.relationship('Complaint', backref='procurement', lazy='dynamic')
    award = db.relationship('Award', backref='procurement', uselist=False)
    replacement = db.relationship('Procurement', remote_side=[id], backref='replaced_by')

    def has_form_d(self):
        return bool(self.form_d_file_path and self.form_d_filename)

    def has_form_e(self):
        return bool(self.form_e_file_path and self.form_e_filename)

    def has_itt(self):
        return bool(self.itt_file_path and self.itt_filename)

    def has_rfq(self):
        return bool(self.rfq_file_path and self.rfq_filename)

    def has_tender_documents(self):
        return self.has_itt() or self.has_rfq()

    @staticmethod
    def ppra_code_options():
        return [
            '100', '101', '102', '103', '104', '105', '106', '107', '111', '112', '113', '114', '115', '116', '117', '118', '119', '120', '127', '128', '129', '130', '131', '132', '133', '134', '135', '136', '137', '138', '139', '140', '141', '142', '143', '144', '145',
            '200', '201', '202', '203', '207', '208', '209', '211', '212', '213', '214', '216', '217', '218',
            '301', '302', '303', '304', '305', '307', '308', '310', '311', '312', '313', '314', '315', '316', '317', '318', '319', '320', '321', '322', '323', '324', '325',
            '01', '02', '03', '05', '06', '08', '09', '10', '13', '14', '15'
        ]

    @staticmethod
    def ppra_sub_code_options():
        return ['00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '20', '21', '22', '23', '24', '25']

    @staticmethod
    def ppra_code_labels():
        lookup = Procurement.ppra_classification_lookup()
        labels = {}
        for code, data in lookup.items():
            label = (data or {}).get('label')
            if code and label:
                labels[str(code)] = str(label)
        return labels

    @staticmethod
    def ppra_classification_lookup():
        return {
            '100': {'label': 'Security Services (100% citizen ALL)', 'subcodes': {'01': 'Security Guard Services (name modified)', '02': 'Specialist Security Service (new)', '03': 'Closed protection Service (new)', '04': 'Electronic Security Service (new)', '05': 'Private Investigation Service (new)', '06': 'Security Advisory Service (new)'}},
            '101': {'label': 'Hotel and Catering (Restaurant) Services', 'subcodes': {'01': 'Hotel (Hotel, Motel, lodge, guest house) services', '02': 'Restaurant and Food-serving services', '03': 'Canteen and Catering services', '04': 'Conference and Workshop services'}},
            '102': {'label': 'Tourism and Travel Related Services', 'subcodes': {'01': 'Travel related services (Travel agencies)', '02': 'Tour operator Services (Tourist information services)', '03': 'Guide services', '04': 'Holiday camp and self-service facilities'}},
            '103': {'label': 'Collection and Disposal of hazardous Material', 'subcodes': {'01': 'Sewage collection, disposal and related services', '02': 'Refuse collection and disposal services', '03': 'Clinical waste collection, disposal and related services', '04': 'Chemical waste collection, disposal and related services', '05': 'Used oil collection, disposal and related services', '06': 'E-waste collection, disposal and related services', '07': 'Scrap metal collection and disposal', '08': 'Arms and Ammunition collection and disposal', '09': 'Radiation material collection and disposal', '10': 'Explosives material collection and disposal', '11': 'Asbestos dismantling and disposal services (new sub-code)'}},
            '104': {'label': 'Maintenance of Vehicles, Machinery and other Services', 'subcodes': {'01': 'Light Vehicles', '02': 'Trucks, Trailers, Buses', '03': 'Hydraulics', '04': 'Tyre Repairs, wheel Alignment and balancing', '05': 'Panel Beating, Spray Painting and Body Protection Services', '06': 'Agricultural Machinery', '07': 'Heavy Machinery', '08': 'Refurbishment', '09': 'Components Overhaul'}},
            '105': {'label': 'Maintenance of Rolling Stock Machinery and other Services', 'subcodes': {'01': 'Locomotives', '02': 'Wagons', '03': 'Passenger Coaches', '04': 'Railway/Road Hoisting/Lifting Equipment', '05': 'Remanufacturing/ Refurbishment', '06': 'Components overhaul'}},
            '106': {'label': 'Material Testing (new code)', 'subcodes': {'01': 'Material Testing'}},
            '107': {'label': 'Motor Vehicle Assessment (new code)', 'subcodes': {'01': 'Motor Vehicle Assessment'}},
            '111': {'label': 'Maintenance of Vehicles Related Equipment', 'subcodes': {'01': 'General machining and welding', '02': 'Hoist/Cranes', '03': 'Exhaust fitment and repairs', '04': 'Air conditioning', '05': 'Upholstery', '06': 'Windscreen, glass fitting and maintenance', '07': 'Propeller shaft repairs and maintenance', '08': 'Radiator service', '09': 'Fuel injector and nozzle service and repair'}},
            '112': {'label': 'Maintenance of Medical Equipment', 'subcodes': {'01': 'Therapeutic and Diagnostic Radiation Equipment, Spares and Consumables', '02': 'Medical and Surgical Equipment, Spares and Accessories'}},
            '113': {'label': 'Aircraft Maintenance', 'subcodes': {'01': 'Airframe, propeller and power plant', '02': 'Instruments and accessories', '03': 'Avionics and Radio', '04': 'Specialized services, upholstery, painting (refurbishments)', '05': 'Non-destructive testing'}},
            '114': {'label': 'Boat Maintenance', 'subcodes': {'01': 'Boat maintenance and repair services'}},
            '115': {'label': 'Office Equipment Maintenance', 'subcodes': {'01': 'Office equipment and accessories'}},
            '116': {'label': 'Broadcasting and Audio-Visual Services', 'subcodes': {'01': 'Installation and maintenance of broadcasting and audio-visual equipment', '02': 'Installation of Studio and Hall Acoustics', '03': 'Remote Broadcast Services & Relaying of Feeds'}},
            '117': {'label': 'Broadcasting Services', 'subcodes': {'01': 'Radio broadcasting', '02': 'Television broadcasting', '03': 'Online Radio Broadcasting (new sub-code)', '04': 'Online Television Broadcasting (new sub-code)'}},
            '118': {'label': 'Telecommunication Services', 'subcodes': {'01': 'Public Telecommunications Services', '02': 'Network Facilities (telecom sites towers, satellite infrastructure fibre etc) (new sub-code)', '03': 'Value Added Services (IP Telephone Least Cost Routing, Conferencing etc) (new sub-code)', '04': 'Radio Communication services (e.g 2-way radio services)', '05': 'Installation and maintenance of Telecommunications equipment and Systems'}},
            '119': {'label': 'Universal Postal Services', 'subcodes': {'01': 'Postal services', '02': 'Courier services'}},
            '120': {'label': 'ICT Technical Support Services', 'subcodes': {'01': 'Systems Development Services and maintenance services', '02': 'Server Management and maintenance Services', '03': 'Data center maintenance & hosting facilities', '04': 'Desktop Management and maintenance Services', '05': 'Network Management and maintenance Services', '06': 'ICT Security Management and maintenance Services', '07': 'Internet Services', '08': 'ICT Risk Management Services', '09': 'Imaging, data capture and migration services'}},
            '127': {'label': 'Insurance & Pension', 'subcodes': {'01': 'Pension funding services', '02': 'Medical aid scheme services', '03': 'Motor vehicle Insurance', '04': 'Freight Insurance services', '05': 'Fire and other property damage insurance', '06': 'Brokerage and risk related Services', '07': 'Life Insurance Services', '08': 'Other Insurance and Pension Services'}},
            '128': {'label': 'Media Services', 'subcodes': {'01': 'Print Media', '02': 'Radio, Film & Television', '03': 'Other media services'}},
            '129': {'label': 'Passenger Transport Services', 'subcodes': {'01': 'Air', '02': 'Land', '03': 'Water', '04': 'Rail'}},
            '130': {'label': 'Freight Services', 'subcodes': {'01': 'Air', '02': 'Land', '03': 'Water', '04': 'Rail', '05': 'Other Transportation Services'}},
            '131': {'label': 'Rental Services', 'subcodes': {'01': 'Accommodation (Office/residential/industrial/commercial)', '02': 'Motor Vehicles', '03': 'Machinery and equipment other than for Transport & Real estate', '04': 'Aircraft', '05': 'Boat', '06': 'Other rental services'}},
            '132': {'label': 'Cleaning Services', 'subcodes': {'01': 'Building cleaning services (including windows, carpets and others)', '03': 'Petroleum storage and equipment cleaning', '04': 'Hazardous Material'}},
            '133': {'label': 'Public Utilities', 'subcodes': {'01': 'Water distribution and related services', '03': 'Electricity distribution and related services', '04': 'Other sources of energy and distribution', '05': 'Meter reading services'}},
            '134': {'label': 'Health Services', 'subcodes': {'01': 'Air ambulance', '02': 'Road ambulance', '03': 'Health Care services (allied health, dentistry, midwifery-obstetrics, medicine, nursing, optometry, pharmacy, psychosocial, physiotherapy, ENT, etc.)', '04': 'Medical laboratory services', '05': 'Veterinary services (including Veterinary laboratory)', '06': 'Psychosocial', '07': 'Forensic laboratory services'}},
            '135': {'label': 'Customs Clearing, forwarding and Shipping', 'subcodes': {'01': 'Customs clearing, forwarding and Shipping'}},
            '136': {'label': 'Auctioneering Services', 'subcodes': {'01': 'Real estate auctioneering', '02': 'Movable auctioneering (plant, equipment, furniture, wildlife and livestock etc)'}},
            '137': {'label': 'Gardening and Landscaping Services', 'subcodes': {'01': 'Gardening, landscaping and maintenance', '02': 'Nursery'}},
            '138': {'label': 'Marketing and Public Relation Services', 'subcodes': {'01': 'Marketing Services', '02': 'Advertising Services (billboards, electronic, internet, signage, infomercials, promotional material – content required)', '03': 'Public relations services'}},
            '139': {'label': 'Miscellaneous Services', 'subcodes': {'01': 'Washing and dry cleaning services', '02': 'Hairdressing and beauty treatment services', '03': 'Physical wellbeing services', '04': 'Entertainment services', '05': 'Provision of call Centre services', '06': 'Library and archives services', '07': 'Secretarial services (Photocopying, binding, faxing, typing etc.)', '08': 'Miscellaneous equipment maintenance services', '09': 'Photography Services', '10': 'Cremation services', '11': 'Embroidery and engraving services', '12': 'Florists services', '13': 'Mobile toilets services', '14': 'Exhibition space rental', '15': 'Mortuary services', '16': 'Event Management Services', '18': 'Graphic Design', '20': 'Master of Ceremonies', '21': 'Rapporteuring', '22': 'Choreography', '23': 'Defence Equipment Maintenance', '24': 'Interior Design and decor', '25': 'Mural Services (Art work)'}},
            '140': {'label': 'Calibration Services', 'subcodes': {'01': 'Equipment Calibration'}},
            '141': {'label': 'Language & Interpretation Services', 'subcodes': {'01': 'Sign Language', '02': 'Interpretation', '03': 'Translation', '04': 'Transcribing'}},
            '142': {'label': 'Aviation Services', 'subcodes': {'01': 'Air Charter', '02': 'Aerial Work', '03': 'Aviation Training'}},
            '143': {'label': 'Human Resources Services', 'subcodes': {'01': 'Recruitment', '02': 'Student placement & management'}},
            '144': {'label': 'Training Services', 'subcodes': {'01': 'Human Resources', '02': 'Animals (Dogs, horses and others)'}},
            '145': {'label': 'Safety Health and Environment Services', 'subcodes': {'01': 'Occupational Health and Safety', '02': 'Maintenance of firefighting equipment', '03': 'Disinfecting and extermination services', '04': 'Explosives Services (new sub code)'}},
            '200': {'label': 'Agriculture Products and Related Equipment', 'subcodes': {'01': 'Stock Feeds and Supplements', '02': 'Veterinary Drugs and Remedies', '03': 'Veterinary Vaccines', '04': 'Seeds, Seedlings and Plants', '05': 'Agricultural Equipment, Instruments, Spares and Accessories (including tractors)', '06': 'Animal Products and By-products (other than food)', '07': 'Agro-chemical products'}},
            '201': {'label': 'Printed Matter and Related Equipment', 'subcodes': {'01': 'Printed Matter (Books, newspapers, journals, postcards, promotional material – content provided etc)', '02': 'Plates, cylinders and other media for use in printing'}},
            '202': {'label': 'Medical Supplies and Related Equipment', 'subcodes': {'01': 'Drugs', '02': 'Vaccines', '03': 'Dressings', '04': 'Medical Consumables, healthcare aids, Surgical and Orthopedic and Laboratory Reagents', '05': 'Medical, Surgical Equipment (Including hospital furniture), Spares and Accessories', '06': 'Therapeutic and Diagnostic Radiation Equipment, Spares and Consumables'}},
            '203': {'label': 'Electrical, Electronic, Mechanical and ICT supplies', 'subcodes': {'01': 'Electrical and Electronic Equipment, Spares and Accessories (includes ICT, photographic equipment and others)', '02': 'Broadcast Transmission Equipment', '03': 'Mechanical Equipment, Machines, Spares and Accessories', '04': 'Fire Fighting Equipment', '05': 'Navigation Equipment, Instruments and Surveillance'}},
            '207': {'label': 'Food Supplies', 'subcodes': {'01': 'General Food Supplies', '02': 'Fresh Produce', '03': 'Dietary Supplements'}},
            '208': {'label': 'Transport Equipment & Accessories', 'subcodes': {'01': 'Motor Vehicles', '02': 'General spares and Accessories (including tyres)', '03': 'Earthmoving Equipment', '04': 'Bicycles, spares and accessories', '05': 'Aircraft, Spares and Accessories', '07': 'Trailers, Animal Drawn Vehicles', '08': 'Boats', '09': 'Motorcycles and Quad bikes'}},
            '209': {'label': 'Railway Transport Equipment & Accessories', 'subcodes': {'01': 'Locomotives', '02': 'Wagons', '03': 'Passenger Coaches', '04': 'Rail Car/Diesel Multiple units', '05': 'Rail/Road Crane', '06': 'Reach Stacker', '07': 'Hoisting/ lifting'}},
            '211': {'label': 'General Supplies', 'subcodes': {'01': 'Chemicals', '02': 'Stationery', '03': 'Art & Crafts', '04': 'Clothing, apparels & fabrics', '05': 'Furniture (including school, domestic office furniture etc)', '06': 'Plastic products', '07': 'Sports and Recreation Equipment, Spares and Accessories', '08': 'Forestry products and equipment', '09': 'Laboratory equipment, spares and accessories eg test tubes, benson burners etc', '10': 'Musical Instruments, audio visual equipment and accessories', '11': 'Toiletry and hygiene products', '12': 'Glass products', '13': 'Mobile toilets', '14': 'Camping equipment and accessories', '15': 'Prefabs', '16': 'Coffins', '17': 'Paper and paperboards', '18': 'Catering Equipment', '19': 'Hardware, Tools and Construction Materials', '20': 'Educational aids (interviews, educational videos, cd\'s, educational charts, braille)', '21': 'Irrigation / gardening water', '22': 'Explosives (new sub code)'}},
            '212': {'label': 'Manufacturers/Producers of Agricultural Products and Related Products', 'subcodes': {'01': 'Stock Feeds and Supplements', '02': 'Veterinary Drugs and Remedies', '03': 'Veterinary Vaccines', '04': 'Seeds, Seedlings and Plants', '05': 'Agricultural Equipment, Instruments, Spares and Accessories (Including tractor)', '06': 'Agro-chemical products', '07': 'Animal Products and By-products (other than food)'}},
            '213': {'label': 'General Manufactures/Producers', 'subcodes': {'01': 'Processed Food', '02': 'Beverages', '03': 'Household products', '04': 'Industrial products', '05': 'Handicraft and art supplies', '06': 'Furniture', '07': 'Construction products (including bricks, paving slabs etc)', '08': 'Hardware products', '09': 'Clothing and fabrics', '10': 'Paper and paperboards', '11': 'Plastic products', '12': 'Drugs', '13': 'Vaccines', '14': 'Printing services', '15': 'Mobile toilets', '16': 'Canvas/Tents', '17': 'Prefabs', '18': 'Coffins', '19': 'Timber products', '20': 'Medical devices, consumables and accessories', '21': 'Glass products', '22': 'Explosives (new sub-code)'}},
            '214': {'label': 'Petroleum Products', 'subcodes': {'01': 'Fuel', '02': 'Oil and Lubricants', '03': 'Coal'}},
            '216': {'label': 'Gases', 'subcodes': {'01': 'Domestic', '02': 'Industrial', '03': 'Medical'}},
            '217': {'label': 'Media Supplies', 'subcodes': {'01': 'Print Media Content', '02': 'Radio, Film and Television Content', '03': 'Other Media Content'}},
            '218': {'label': 'Psychosocial Material', 'subcodes': {'01': 'Psychosocial Material'}},
            '301': {'label': 'Architecture Services', 'subcodes': {'01': 'Architecture services'}},
            '302': {'label': 'Quantity Surveying Services', 'subcodes': {'01': 'Quantity surveying services'}},
            '303': {'label': 'Civil Engineering Services', 'subcodes': {'01': 'Roads', '02': 'Bridges', '03': 'Infrastructure', '04': 'Civil/Structural Engineering', '05': 'Dams', '06': 'Railways', '07': 'Airports', '08': 'Irrigation, water supply and sanitation/sewerage', '09': 'Transportation'}},
            '304': {'label': 'Electrical Engineering Services', 'subcodes': {'01': 'Electrical design-general'}},
            '305': {'label': 'Mechanical Engineering Services', 'subcodes': {'01': 'Mechanical design-general'}},
            '307': {'label': 'Mining Engineering Services', 'subcodes': {'01': 'Mining Engineering Services'}},
            '308': {'label': 'Building Engineering Services', 'subcodes': {'01': 'Clerk of works services', '02': 'Wet services', '03': 'Facilities management'}},
            '310': {'label': 'Surveying Services', 'subcodes': {'01': 'Land, Topographic Survey Road and Utilities Alignment', '02': 'Mapping Services (Photogrammetric and Cartographic)', '03': 'Geographic Information Systems (GIS) and Data Management Process'}},
            '311': {'label': 'Project Management Services', 'subcodes': {'01': 'General Project Management', '02': 'Construction Project Management'}},
            '312': {'label': 'Civil Aviation/Meteorological Electronics Services', 'subcodes': {'01': 'Navigational aids/ Meteorological electronics', '02': 'Aviation meteorology', '03': 'Aviation consultancy'}},
            '313': {'label': 'Environmental Services', 'subcodes': {'01': 'Environmental assessments', '02': 'Archaeological services', '03': 'Environmental engineering and monitoring services', '04': 'Environmental management systems', '05': 'Natural resource planning and management', '06': 'Environmental policy and legislation', '07': 'Auditing and monitoring services'}},
            '314': {'label': 'Finance Related Services', 'subcodes': {'01': 'Finance management', '02': 'Banking management', '03': '(blank / not specified)', '04': 'Company secretarial services', '05': 'Payroll management services', '06': 'Auditing services', '07': 'Accounting services'}},
            '315': {'label': 'Human Resource Services', 'subcodes': {'01': 'Organisation design and change management', '02': 'Job evaluation, compensation & reward management', '03': 'Human resources policy'}},
            '316': {'label': 'Real Estate Services', 'subcodes': {'01': 'Property management', '02': 'Estate agency', '03': 'Property valuation and rating', '04': 'Property consultancies', '05': 'Property development and sales'}},
            '317': {'label': 'Other Consultancy Services', 'subcodes': {'01': 'Management Consultancy Services', '02': 'Education research consultancy', '03': 'Supply Chain Management Services', '04': 'Socio-economic consulting services', '05': 'Media and Public Relations consultancy', '06': 'Fleet management', '07': 'Health consultancy services', '08': 'Sensitive and Security Consultancy', '09': 'Agricultural consultancy', '10': 'Fraud and risk analysis', '11': 'Forensic Investigation services', '12': 'Interior Design', '13': 'Landscape Design'}},
            '318': {'label': 'Legal Services', 'subcodes': {'01': 'Legal services', '02': 'Conveyancing', '03': 'Notary public'}},
            '319': {'label': 'ICT Consultancy Services', 'subcodes': {'01': 'ICT System Development', '02': 'Network and Facilities Management (ICT)', '03': 'ICT Security Management', '04': 'ICT Risk Management', '05': 'Telecommunications', '06': 'Broadcasting'}},
            '320': {'label': 'Town and Regional Planning', 'subcodes': {'01': 'Urban & Regional Planning', '02': 'Transport Planning', '03': 'Urban Design'}},
            '321': {'label': 'Dispute Resolution Services', 'subcodes': {'01': 'Arbitration', '02': 'Mediation'}},
            '322': {'label': 'Health Care Consulting Services', 'subcodes': {'01': 'Clinical', '02': 'Guidance and Counseling', '03': 'Medical Equipment Resources and Management'}},
            '323': {'label': 'Energy Management Services (EMS) (new code)', 'subcodes': {'01': 'Energy System Design, Measurement and Auditing (Renewable Energy and Energy Management etc)'}},
            '324': {'label': 'Fire Engineering Services (new code)', 'subcodes': {'01': 'Fire Risk Assessment'}},
            '325': {'label': 'Geological Services (new code)', 'subcodes': {'01': 'Geoscience Services (Borehole Siting Logging)', '02': 'Hydrogeology (groundwater mapping)', '03': 'Geotechnical services'}},
            '01': {'label': 'Building Construction Works and Maintenance', 'subcodes': {'01': 'Building Construction', '02': 'Structural steel work', '03': 'Pre-fabricated buildings'}},
            '02': {'label': 'Electrical Engineering Works and Maintenance', 'subcodes': {'01': 'Electrical Installations', '02': 'High voltage reticulation', '03': 'Airfield lighting', '04': 'Automated machinery and control systems', '05': 'Photovoltaic systems', '06': 'Fire detection systems', '07': 'Security systems installations (CCTV, Access Control, Alarms etc.)', '08': 'Radio/Telemetry'}},
            '03': {'label': 'Civil Engineering Works', 'subcodes': {'01': 'Construction (Roads, Infrastructure, Airfields and Railways)', '02': 'Rail track / permanent way', '03': 'Dams', '04': 'Road surfacing', '05': 'Bridges', '06': 'Water supplies, sanitation reticulation and Irrigation works'}},
            '05': {'label': 'Water and Sewage Treatment Plant Works', 'subcodes': {'01': 'Water and sewage treatment plants'}},
            '06': {'label': 'Specialized Construction Works', 'subcodes': {'01': 'Sports fields (turf and running track)', '02': 'Piling/Underpinning/Pipe jacking etc', '03': 'Water proofing', '04': 'Swimming Pools', '05': 'Installation, maintenance and decommissioning of telecommunication infrastructure'}},
            '08': {'label': 'Mechanical Engineering Works and Maintenance', 'subcodes': {'01': 'Air conditioning/Refrigeration systems', '02': 'Solar water heating', '03': 'Lifts, hoists and escalators', '04': 'Fire suppression systems', '05': 'Compressed air equipment installation', '06': 'Liquid petroleum gas installations and equipment', '07': 'Low pressure water systems', '08': 'Steam and boiler systems', '09': 'Laundry and kitchen equipment installation and services', '10': 'General fabrication and machine shop services', '11': 'Pumps and munchers'}},
            '09': {'label': 'Drilling Works', 'subcodes': {'01': 'Drilling, borehole development and Equipping', '02': 'Test pumping'}},
            '10': {'label': 'Water Engineering Works', 'subcodes': {'01': 'Storage tanks'}},
            '13': {'label': 'Fencing - buildings, roads and others (100% Citizen)', 'subcodes': {'01': 'Fencing Works', '02': 'Electrical Fencing'}},
            '14': {'label': 'Roads - Ancillary Works (100% Citizen)', 'subcodes': {'01': 'Road marking', '02': 'Signs', '03': 'Road routine maintenance (Labour based)', '04': 'Road Guard rails/Kerbing', '05': 'Road Bush Clearing/de-stumping'}},
            '15': {'label': 'Civil Aviation /Meteorological Electronics Works', 'subcodes': {'01': 'Navigational aids', '02': 'Aeronautical communications', '03': 'Aviation meteorology'}}
        }

    @staticmethod
    def ppra_sub_codes_for(code):
        code_key = str(code or '').strip().split('-', 1)[0]
        lookup = Procurement.ppra_classification_lookup()
        code_data = lookup.get(code_key, {})
        return list((code_data.get('subcodes') or {}).keys())

    @staticmethod
    def ppra_description_for(code, sub_code=None):
        normalised_code = str(code or '').strip()
        if not normalised_code:
            return ''
        code_key = normalised_code.split('-', 1)[0]
        sub_key = str(sub_code or '').strip() if sub_code else ''
        if '-' in normalised_code and not sub_key:
            sub_key = normalised_code.split('-', 1)[1]
        lookup = Procurement.ppra_classification_lookup()
        data = lookup.get(code_key, {})
        label = (data.get('label') or '').strip()
        subcodes = data.get('subcodes') or {}
        if sub_key and sub_key != '00' and sub_key.lower() != 'none':
            sub_description = subcodes.get(sub_key)
            if sub_description:
                if label:
                    return f"{label} - {sub_description}"
                return str(sub_description)
        return label

    @staticmethod
    def ppra_description(code, sub_code=None):
        return Procurement.ppra_description_for(code, sub_code)

    def full_ppra_code(self):
        code = (self.ppra_code or '').strip()
        if self.ppra_sub_code and self.ppra_sub_code not in ('00', 'none'):
            if code and not code.endswith(f'-{self.ppra_sub_code}'):
                return f'{code}-{self.ppra_sub_code}'
            return self.ppra_sub_code if not code else code
        return code

    def status_label(self):
        return self.status.replace('_', ' ').title()

    def bid_count(self):
        return self.submissions.filter_by(status='submitted').count()

    def committee_chair(self):
        return self.committee_members.filter_by(role='chair').first()

    def can_committee_member_access(self, committee_member):
        return bool(committee_member and committee_member.is_access_active())

    def can_transition_to_contract(self):
        if self.status not in ('award_published', 'cooling_off', 'complaint_hold', 'ready_for_contract'):
            return False

        if self.award and self.award.cooling_off_active():
            return False

        active_complaints = list(self.complaints) if hasattr(self, 'complaints') else []
        unresolved = [
            complaint for complaint in active_complaints
            if getattr(complaint, 'status', None) in ('received', 'under_review', 'escalated')
        ]
        return not unresolved

    def check_governance_rules(self, direct_threshold=500000, open_threshold=500000):
        result = {'errors': [], 'warnings': []}
        total_value = float(self.estimated_value or 0)

        lots = list(self.lots) if hasattr(self, 'lots') else []
        lot_total = 0.0
        for lot in lots:
            try:
                lot_total += float(lot.estimated_value or 0)
            except (TypeError, ValueError):
                continue

        if self.method == 'direct' and total_value > direct_threshold:
            result['errors'].append('direct_procurement_exceeds_threshold')

        if self.method in ('open_domestic', 'open_international', 'rfp', 'rfq') and total_value > open_threshold:
            result['warnings'].append('open_procurement_high_value_review')

        if len(lots) > 1 and total_value >= open_threshold:
            result['warnings'].append('lot_splitting_risk')

        if len(lots) > 1 and lot_total >= direct_threshold:
            result['warnings'].append('lot_splitting_risk')

        return result

    @classmethod
    def ensure_schema_columns(cls):
        from sqlalchemy import text
        for column_name, column_sql in {
            'procurement_entity': 'ALTER TABLE procurements ADD COLUMN procurement_entity VARCHAR(200)',
            'ppra_sub_code': 'ALTER TABLE procurements ADD COLUMN ppra_sub_code VARCHAR(20)',
            'clarification_deadline': 'ALTER TABLE procurements ADD COLUMN clarification_deadline DATETIME',
            'tender_fee': 'ALTER TABLE procurements ADD COLUMN tender_fee NUMERIC(15, 2) DEFAULT 0.00',
            'form_d_file_path': 'ALTER TABLE procurements ADD COLUMN form_d_file_path VARCHAR(500)',
            'form_d_filename': 'ALTER TABLE procurements ADD COLUMN form_d_filename VARCHAR(300)',
            'form_e_file_path': 'ALTER TABLE procurements ADD COLUMN form_e_file_path VARCHAR(500)',
            'form_e_filename': 'ALTER TABLE procurements ADD COLUMN form_e_filename VARCHAR(300)',
            'itt_file_path': 'ALTER TABLE procurements ADD COLUMN itt_file_path VARCHAR(500)',
            'itt_filename': 'ALTER TABLE procurements ADD COLUMN itt_filename VARCHAR(300)',
            'rfq_file_path': 'ALTER TABLE procurements ADD COLUMN rfq_file_path VARCHAR(500)',
            'rfq_filename': 'ALTER TABLE procurements ADD COLUMN rfq_filename VARCHAR(300)',
        }.items():
            try:
                probe = f'SELECT {column_name} FROM procurements LIMIT 1' if db.engine.name == 'sqlite' else f'SELECT TOP 1 {column_name} FROM procurements'
                db.session.execute(text(probe))
            except Exception:
                if db.engine.name != 'sqlite':
                    column_sql = column_sql.replace(' ADD COLUMN ', ' ADD ')
                db.session.execute(text(column_sql))
        db.session.commit()

    @classmethod
    def ensure_submission_columns(cls):
        from sqlalchemy import text
        for column_name, column_sql in {
            'compliance_document_path': 'ALTER TABLE submissions ADD COLUMN compliance_document_path VARCHAR(500)',
            'compliance_document_filename': 'ALTER TABLE submissions ADD COLUMN compliance_document_filename VARCHAR(300)',
            'compliance_document_hash': 'ALTER TABLE submissions ADD COLUMN compliance_document_hash VARCHAR(64)',
            'returnable_document_path': 'ALTER TABLE submissions ADD COLUMN returnable_document_path VARCHAR(500)',
            'returnable_document_filename': 'ALTER TABLE submissions ADD COLUMN returnable_document_filename VARCHAR(300)',
            'returnable_document_hash': 'ALTER TABLE submissions ADD COLUMN returnable_document_hash VARCHAR(64)',
        }.items():
            try:
                probe = f'SELECT {column_name} FROM submissions LIMIT 1' if db.engine.name == 'sqlite' else f'SELECT TOP 1 {column_name} FROM submissions'
                db.session.execute(text(probe))
            except Exception:
                if db.engine.name != 'sqlite':
                    column_sql = column_sql.replace(' ADD COLUMN ', ' ADD ')
                db.session.execute(text(column_sql))
        db.session.commit()

    def __repr__(self):
        return f'<Procurement {self.tender_number}>'


class Lot(db.Model):
    """Optional sub-division of a procurement (SOAR FR-INIT-007: lot splitting)."""
    __tablename__ = 'lots'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    lot_number = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    estimated_value = db.Column(db.Numeric(15, 2))

    def __repr__(self):
        return f'<Lot {self.lot_number}>'
