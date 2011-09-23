#!/bin/env python
"""
A High-throughput RNA-seq analysis workflow.

"""
import os, sys, json, getopt
from bbcflib import rnaseq, frontend, common, mapseq, genrep, email
from bein.util import use_pickle, unique_filename_in
from bein import program, execution, MiniLIMS

usage = """run_rnaseq.py [-h] [-u via] [-w wdir] [-k job_key] [-c config_file] [-d minilims] [-m minilims] [-t target]
E.g. >>> python run_rnaseq.py -u lsf -c config_files/jobbamtest.txt -m archive/RNAseq_full -d rnaseq

-h           Print this message and exit
-u via       Run executions using method 'via' (can be 'local' or 'lsf')
-w wdir      Create execution working directories in wdir
-d minilims  MiniLIMS where RNAseq executions and files will be stored.
-m minilims  MiniLIMS where a previous Mapseq execution and files has been stored.
             Set it to None to align de novo from read files.
-k job_key   Alphanumeric key specifying the job
-c file      Config file
-t target    Target features, inside of quotes, separated by spaces. E.g. 'genes exons transcripts'
"""

class Usage(Exception):
    def __init__(self,  msg):
        self.msg = msg

def results_to_json(lims, exid):
    """Create a JSON string describing the results of execution *exid*.

    The execution is sought in *lims*, and all its output files and
    their descriptions are written to the string.
    """
    produced_file_ids = lims.search_files(source=('execution',exid))
    d = dict([(lims.fetch_file(i)['description'], lims.path_to_file(i))
              for i in produced_file_ids])
    j = json.dumps(d)
    return j

def main(argv=None):
    via = "lsf"
    limspath = None
    ms_limspath = "/data/htsstation/mapseq/mapseq_minilims"
    hts_key = None
    working_dir = os.getcwd()
    bam_files = None
    target = None
    map_args = None # {'bwt_args':["-n",str(3),"-p",str(4),"-l",str(50),"--chunkmbs",str(1024),"-m",str(5)]}

    if argv is None:
        argv = sys.argv
    try:
        try:
            opts,args = getopt.getopt(sys.argv[1:],"hu:k:d:m:w:c:t:",
                ["help","via=","key=","minilims=","mapseq_minilims=","working-directory=","config=","target="])
        except getopt.error, msg:
            raise Usage(msg)
        for o, a in opts:
            if o in ("-h", "--help"):
                print __doc__
                print usage
                sys.exit(0)
            elif o in ("-u", "--via"):
                if a=="local": via = "local"
                elif a=="lsf": via = "lsf"
                else: raise Usage("Via (-u) can only be \"local\" or \"lsf\", got %s." % (a,))
            elif o in ("-w", "--working-directory"):
                if os.path.exists(a):
                    os.chdir(a)
                    working_dir = a
                else: raise Usage("Working directory '%s' does not exist." % a)
            elif o in ("-d", "--minilims"):
                limspath = a
            elif o in ("-m", "--mapseq_minilims"):
                ms_limspath = a
		if ms_limspath == 'None': ms_limspath = None
            elif o in ("-k", "--key"):
                hts_key = a
            elif o in ("-c", "--config"):
                config_file = a
            elif o in ("-t", "--target"):
                target = a
            else: raise Usage("Unhandled option: " + o)

        if len(args) != 0:
            raise Usage("workflow.py takes no arguments without specifiers [-x arg].")
        if limspath == None:
            raise Usage("Must specify a MiniLIMS to attach to")
        if target: target = target.split()
        

        # Rna-seq job configuration
        M = MiniLIMS(limspath)
        if hts_key:
            gl = use_pickle( M, "global variables" )
            htss = frontend.Frontend( url=gl['hts_rnaseq']['url'] )
            job = htss.job( hts_key )
            [M.delete_execution(x) for x in M.search_executions(with_description=hts_key,fails=True)]
        elif os.path.exists(config_file):
            (job,gl) = frontend.parseConfig( config_file )
            hts_key = "No job description"
        else: raise ValueError("Need either a job key (-k) or a configuration file (-c).")
            
        job.options['ucsc_bigwig'] = job.options.get('ucsc_bigwig') or True
        job.options['gdv_project'] = job.options.get('gdv_project') or False
        job.options['discard_pcr_duplicates'] = job.options.get('discard_pcr_duplicates') or False
        assembly_id = job.assembly_id
        g_rep = genrep.GenRep( gl['genrep_url'], gl.get('bwt_root'), intype=1 )
            #intype is for mapping on the exons (intype=1) or transcriptome (intype=2)
        assembly = g_rep.assembly(assembly_id)

        # Retrieve mapseq output
        mapseq_url = None
        if 'hts_mapseq' in gl:
            mapseq_url = gl['hts_mapseq']['url']


        # Program body #
        with execution(M, description=hts_key, remote_working_directory=working_dir ) as ex:
            if ms_limspath:
                print "Loading BAM files..."
                (bam_files, job) = mapseq.get_bam_wig_files(ex, job, minilims=ms_limspath, hts_url=mapseq_url,
                                                        script_path=gl.get('script_path') or '', via=via )
                print "Loaded."
            else:
                print "Alignment..."
                job = mapseq.get_fastq_files( job, ex.working_directory)
                fastq_root = os.path.abspath(ex.working_directory)
                bam_files = mapseq.map_groups(ex, job, fastq_root, assembly_or_dict=assembly, map_args=map_args)
                print "Reads aligned."
            print "Starting"
            print "Current working directory:", ex.working_directory
            rnaseq.rnaseq_workflow(ex, job, assembly, bam_files,
                            target=target, via=via)
        # End of program body #


        results_to_json(M, ex.id)

        allfiles = common.get_files(ex.id, M)
        if 'gdv_project' in job.options and 'sql' in allfiles:
            allfiles['url'] = {job.options['gdv_project']['public_url']: 'GDV view'}
            download_url = gl['hts_rnapseq']['download']
            [gdv.add_gdv_track( gl['gdv']['key'], gl['gdv']['email'],
                                job.options['gdv_project']['project_id'],
                                url=download_url+str(k), 
                                name = re.sub('\.sql','',str(f)),
                                gdv_url=gl['gdv']['url'] ) 
             for k,f in allfiles['sql'].iteritems()]
        print json.dumps(allfiles)
        if 'email' in gl:
            r = email.EmailReport( sender=gl['email']['sender'],
                                   to=str(job.email),
                                   subject="RNA-seq job "+str(job.description),
                                   smtp_server=gl['email']['smtp'] )
            r.appendBody('''
Your RNA-seq job is finished. \n
The description was: 
'''+str(job.description)+'''
and its unique key is '''+hts_key+'''.\n
You can retrieve the results at this url:
'''+gl['hts_chipseq']['url']+"jobs/"+hts_key+"/get_results")
            r.send()

        sys.exit(0)
    except Usage, err:
        print >>sys.stderr, err.msg
        print >>sys.stderr, usage
        return 2


if __name__ == '__main__':
    sys.exit(main())
