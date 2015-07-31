#!/usr/bin/env python

"""
Annotate and import solved 3D structures into MongoDB
"""

import sys, os, math, datetime
from pyrna.task import Task
from pyrna.db import RNA3DHub, PDB, PDBQuery
from pyrna import parsers
from pyrna.computations import Rnaview
from bson.objectid import ObjectId
from pymongo import MongoClient

def import_3Ds(db_host = 'localhost', db_port = 27017, rna3dhub = False, canonical_only = True, annotate = False, limit = 5000):
    client = MongoClient(db_host, db_port)
    db_name = ""

    if rna3dhub:
        rna3dHub = RNA3DHub()
        db_name = "RNA3DHub"
    else:
        rna3dHub = None
        db_name = "PDB"

    db = client[db_name]
    structuresPerJob = 100

    total_structures = 0
    if not rna3dhub:
        query ="""<orgPdbQuery>
    <version>head</version>
    <queryType>org.pdb.query.simple.ChainTypeQuery</queryType>
    <description>Chain Type: there is a Protein and a RNA chain but not any DNA or Hybrid</description>
    <containsProtein>Y</containsProtein>
    <containsDna>N</containsDna>
    <containsRna>Y</containsRna>
    <containsHybrid>N</containsHybrid>
  </orgPdbQuery>"""
        total_structures = len(PDB().query(query))
    else:
        total_structures = len(RNA3DHub().get_clusters())

    print "%i 3Ds to process"%total_structures

    total_jobs = int(math.floor(total_structures/100)+1) #100 structures per job

    for job_id in range (1, total_jobs+1):
        doTheJob(job_id, db, rna3dHub, annotate, structuresPerJob, total_structures, limit)

def doTheJob(job_id, db, rna3dHub, annotate, structuresPerJob, total_structures, limit):
    pdb = PDB()
    rnaview = Rnaview()

    start = (job_id-1)*structuresPerJob+1
    end = (job_id-1)*structuresPerJob+1+structuresPerJob-1

    if rna3dHub:

        clusters = rna3dHub.get_clusters()
        print clusters

        if end > len(clusters):
            end = len(clusters)

        for cluster in clusters['pdb-ids'][start:end]:
            if db['tertiaryStructures'].find_one({'source':"db:pdb:%s"%cluster[0]}):
                continue
            print "Recover %s"%cluster[0] #we use the first pdb_id in the list of ids making a cluster
            for ts in parsers.parse_pdb(pdb.get_entry(cluster[0])):
                try:
                    ss = None
                    if annotate:
                        ss, ts = rnaview.annotate(ts, canonical_only = canonical_only)
                    save(db, ss, ts, cluster[0], limit)

                except Exception, e:
                    print "No annotation for %s"%cluster[0]

    else:
        query = """
        <orgPdbQuery>
<version>head</version>
<queryType>org.pdb.query.simple.ChainTypeQuery</queryType>
<description>Chain Type: there is a Protein and a RNA chain but not any DNA or Hybrid</description>
<containsProtein>Y</containsProtein>
<containsDna>N</containsDna>
<containsRna>Y</containsRna>
<containsHybrid>N</containsHybrid>
</orgPdbQuery>
        """
        pdb_ids = PDB().query(query)
        for pdb_id in pdb_ids[start:end]:
            if db['tertiaryStructures'].find_one({'source':"db:pdb:%s"%pdb_id}):
                continue
            print "Recover %s"%pdb_id
            for ts in parsers.parse_pdb(pdb.get_entry(pdb_id)):
                try:
                    ss = None
                    if annotate:
                        ss, ts = rnaview.annotate(ts, canonical_only = canonical_only)
                    save(db, ss, ts, pdb_id, limit)

                except Exception, e:
                    print e
                    print "No annotation for %s"%pdb_id

def save(db, secondary_structure, tertiary_structure, pdbId, limit):

    if db['junctions'].count() >= limit:
        print "Limit of %i junctions reached"%limit
        sys.exit()

    tertiary_structure.source="db:pdb:%s"%pdbId

    if secondary_structure:

        computation = {
            'inputs': [tertiary_structure._id+"@tertiaryStructures"],
            'outputs': [secondary_structure._id+"@secondaryStructures"],
            'tool': "tool:rnaview:N.A.",
            'date': str(datetime.datetime.now())
        }

        if secondary_structure.rna == tertiary_structure.rna:
            ncRNA = {
                '_id': secondary_structure.rna._id,
                'source': secondary_structure.rna.source,
                'name': secondary_structure.rna.name,
                'sequence': secondary_structure.rna.sequence,
            }
            if not db['ncRNAs'].find_one({'_id':ncRNA['_id']}):
                db['ncRNAs'].insert(ncRNA)
        else:
            ncRNA = {
                '_id': secondary_structure.rna._id,
                'source': secondary_structure.rna.source,
                'name': secondary_structure.rna.name,
                'sequence': secondary_structure.rna.sequence,
            }
            if not db['ncRNAs'].find_one({'_id':ncRNA['_id']}):
                db['ncRNAs'].insert(ncRNA)
            ncRNA = {
                '_id': tertiary_structure.rna._id,
                'source': tertiary_structure.rna.source,
                'name': tertiary_structure.rna.name,
                'sequence': tertiary_structure.rna.sequence,
            }
            if not db['ncRNAs'].find_one({'_id':ncRNA['_id']}):
                db['ncRNAs'].insert(ncRNA)

        secondary_structure.find_junctions()

        ss_descr = {
            '_id': secondary_structure._id,
            'source': secondary_structure.source,
            'name': secondary_structure.name,
            'rna': secondary_structure.rna._id+"@ncRNAs"
        }

        helices_descr = []
        for helix in secondary_structure.helices:
            helix_desc = {
                'name': helix['name'],
                'location': helix['location']
            }
            if helix.has_key('interactions'):
                interactions_descr = []
                for interaction in helix['interactions']:
                    interactions_descr.append({
                        'orientation': interaction['orientation'],
                        'edge1': interaction['edge1'],
                        'edge2': interaction['edge2'],
                        'location': interaction['location']
                    })
                helix_desc['interactions'] = interactions_descr

            helices_descr.append(helix_desc)

        ss_descr['helices'] = helices_descr

        single_strands_descr = []
        for single_strand in secondary_structure.single_strands:
            single_strands_descr.append({
                'name': single_strand['name'],
                'location': single_strand['location']
            })

        ss_descr['singleStrands'] = single_strands_descr

        tertiary_interactions_descr = []
        for tertiary_interaction in secondary_structure.tertiary_interactions:
            tertiary_interactions_descr.append({
                'orientation': tertiary_interaction['orientation'],
                'edge1': tertiary_interaction['edge1'],
                'edge2': tertiary_interaction['edge2'],
                'location': tertiary_interaction['location']
            })

        ss_descr['tertiaryInteractions'] = tertiary_interactions_descr

        db['secondaryStructures'].insert(ss_descr)

    ncRNA = {
        '_id': tertiary_structure.rna._id,
        'source': tertiary_structure.rna.source,
        'name': tertiary_structure.rna.name,
        'sequence': tertiary_structure.rna.sequence,
    }
    if not db['ncRNAs'].find_one({'_id':ncRNA['_id']}):
        db['ncRNAs'].insert(ncRNA)

    ts_descr = {
        '_id': tertiary_structure._id,
        'source': tertiary_structure.source,
        'name': tertiary_structure.name,
        'rna': tertiary_structure.rna._id+"@ncRNAs",
        'numbering-system': tertiary_structure.numbering_system
    }

    residues_descr = {}
    keys=[]
    for k in tertiary_structure.residues:
        keys.append(k)

    keys.sort() #the absolute position are sorted

    for key in keys:
        atoms = tertiary_structure.residues[key]['atoms']

        atoms_descr = []

        for atom in atoms:
            atoms_descr.append({
                'name': atom['name'],
                'coords': atom['coords']
            })
        residues_descr[str(key)] = {
            'atoms': atoms_descr
        }

    ts_descr['residues'] = residues_descr

    if not db['tertiaryStructures'].find_one({'_id':ts_descr['_id']}):
        db['tertiaryStructures'].insert(ts_descr)

        if secondary_structure:

            for junction in secondary_structure.junctions:
                junction_descr = {
                    '_id': str(ObjectId()),
                    'molecule': secondary_structure.rna._id+"@ncRNAs",
                    'tertiary-structure': {
                        'id':tertiary_structure._id+'@tertiaryStructures',
                        'source': tertiary_structure.source
                    },
                    'description': junction['description'],
                    'location': junction['location']
                }
                computation['outputs'].append(junction_descr['_id']+"@junctions")

                db['junctions'].insert(junction_descr)

            db['computations'].insert(computation)

if __name__ == '__main__':
    db_host = 'localhost'
    db_port = 27017
    rna3dhub = False
    canonical_only = False
    limit=5000

    if "-h" in sys.argv:
        db_host = sys.argv[sys.argv.index("-h")+1]
    if "-p" in sys.argv:
        db_port = int(sys.argv[sys.argv.index("-p")+1])
    if "-l" in sys.argv:
        limit = int(sys.argv[sys.argv.index("-l")+1])
    rna3dhub =  "-rna3dhub" in sys.argv
    canonical_only =  "-canonical_only" in sys.argv
    annotate = "-annotate" in sys.argv

    import_3Ds(db_host = db_host, db_port = db_port, rna3dhub = rna3dhub, canonical_only = canonical_only, annotate = annotate, limit = limit)
