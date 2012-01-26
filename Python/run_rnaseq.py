#!/usr/bin/env python
"""
A High-throughput RNA-seq analysis workflow.

python run_rnaseq.py -v lsf -c config_files/gapdh.txt -d rnaseq -p transcripts
python run_rnaseq.py -v lsf -c config_files/rnaseq.txt -d rnaseq -p genes -m /scratch/cluster/monthly/jdelafon/mapseq
"""
import os, sys, json, re
import optparse
from bbcflib import rnaseq, frontend, common, mapseq, genrep, email, gdv
from bein.util import use_pickle, add_pickle
from bein import execution, MiniLIMS

class Usage(Exception):
    def __init__(self,  msg):
        self.msg = msg

def main():
    opts = (("-v", "--via", "Run executions using method 'via' (can be 'local' or 'lsf')", {'default': "lsf"}),
            ("-k", "--key", "Alphanumeric key of the new RNA-seq job", {'default': None}),
            ("-d", "--rnaseq_minilims", "MiniLIMS where RNAseq executions and files will be stored.",
                                     {'default': "/data/htsstation/rnaseq/rnaseq_minilims"}),
            ("-m", "--mapseq_minilims", "MiniLIMS where a previous Mapseq execution and files has been stored. \
                                     Set it to None to align de novo from read files.",
                                     {'default': "/data/htsstation/mapseq/mapseq_minilims"}),
            ("-w", "--working-directory", "Create execution working directories in wdir",
                                     {'default': os.getcwd(), 'dest':"wdir"}),
            ("-c", "--config", "Config file", {'default': None}),
            ("-p", "--pileup_level", "Target features, inside of quotes, separated by commas.\
                                     E.g. 'genes,exons,transcripts'",{'default': "genes,exons,transcripts"}),
            ("-u", "--unmapped", "If True, add junction reads to the pileups.",
                                     {'action':'store_true', 'default': False}))
    try:
        usage = "run_rnaseq.py [OPTIONS]"
        desc = """A High-throughput RNA-seq analysis workflow. It returns a file containing
                  a column of transcript counts for each given BAM file, normalized using DESeq's
                  size factors. """
        parser = optparse.OptionParser(usage=usage, description=desc)
        for opt in opts:
            parser.add_option(opt[0],opt[1],help=opt[2],**opt[3])
        (opt, args) = parser.parse_args()

        if os.path.exists(opt.wdir): os.chdir(opt.wdir)
        else: parser.error("Working directory '%s' does not exist." % opt.wdir)
        if not opt.rnaseq_minilims: parser.error("Must specify a MiniLIMS to attach to")

        # RNA-seq job configuration
        M = MiniLIMS(opt.rnaseq_minilims)
        if opt.key:
            gl = use_pickle( M, "global variables" )
            htss = frontend.Frontend( url=gl['hts_rnaseq']['url'] )
            job = htss.job(opt.key) # new *RNA-seq* job instance
            [M.delete_execution(x) for x in M.search_executions(with_description=opt.key,fails=True)]
            unmapped = True
        elif os.path.exists(opt.config):
            (job,gl) = frontend.parseConfig(opt.config)
            unmapped = opt.unmapped
        else: raise ValueError("Need either a job key (-k) or a configuration file (-c).")
        description = opt.key or opt.config
        pileup_level = opt.pileup_level.split(',')

        job.options['unmapped'] = job.options.get('unmapped',True)
        job.options['ucsc_bigwig'] = job.options.get('ucsc_bigwig',True)
        job.options['create_gdv_project'] = job.options.get('create_gdv_project',False)
        if isinstance(job.options['create_gdv_project'],str):
            job.options['create_gdv_project'] = job.options['create_gdv_project'].lower() in ['1','true','t']
        job.options['discard_pcr_duplicates'] = False
        g_rep = genrep.GenRep( gl.get('genrep_url'), gl.get('bwt_root') )
            #intype is for mapping on the genome (intype=0), exons (intype=1) or transcriptome (intype=2)
        assembly = genrep.Assembly(assembly=job.assembly_id, genrep=g_rep, intype=1)
        logfile = open((opt.key or opt.config)+".log",'w')
        logfile.write(json.dumps(gl)+"\n");logfile.flush()

        # Retrieve mapseq output
        mapseq_url = None
        if 'hts_mapseq' in gl: mapseq_url = gl['hts_mapseq']['url']

        # Program body #
        with execution(M, description=description, remote_working_directory=opt.wdir ) as ex:
            logfile.write("Enter execution. Current working directory: %s \n" % ex.working_directory);logfile.flush()
            logfile.write("Fetch bam and wig files");logfile.flush()
            print "Current working directory:", ex.working_directory
            print "Loading BAM files..."
            (bam_files, job) = mapseq.get_bam_wig_files(ex, job, minilims=opt.mapseq_minilims, hts_url=mapseq_url,
                                        script_path=gl.get('script_path',''), via=opt.via, fetch_unmapped=unmapped)
            assert bam_files, "Bam files not found."
            print "Loaded."
            logfile.write("Starting workflow.\n");logfile.flush()
            rnaseq.rnaseq_workflow(ex, job, assembly, bam_files, pileup_level=pileup_level, via=opt.via, unmapped=unmapped)

            gdv_project = {}
            if job.options.get('create_gdv_project'):
                logfile.write("Creating GDV project.\n");logfile.flush()
                gdv_project = gdv.new_project( gl['gdv']['email'], gl['gdv']['key'],
                                               job.description, assembly.id, gl['gdv']['url'] )
                add_pickle( ex, gdv_project, description=common.set_file_descr("gdv_json",step='gdv',type='py',view='admin') )

        # GDV
        allfiles = common.get_files(ex.id, M)
        if re.search(r'success',gdv_project.get('message','')) and 'sql' in allfiles:
            gdv_project_url = gl['gdv']['url']+"public/project?k="+str(gdv_project['project']['key']) \
                              +"&id="+str(gdv_project['project']['id'])
            allfiles['url'] = {gdv_project_url: 'GDV view'}
            download_url = gl['hts_rnaseq']['download']
            urls  = [download_url+str(k) for k in allfiles['sql'].keys()]
            names = [re.sub('\.sql.*','',str(f)) for f in allfiles['sql'].values()]
            logfile.write("Uploading GDV tracks:\n"+" ".join(urls)+"\n"+" ".join(names)+"\n");logfile.flush()
            for nurl,url in enumerate(urls):
                try:
                    gdv.new_track( gl['gdv']['email'], gl['gdv']['key'],
                                   project_id=gdv_project['project']['id'],
                                   url=url, file_names=names[nurl],
                                   serv_url=gl['gdv']['url'] )
                except: pass

        logfile.close()
        print json.dumps(allfiles)

        # E-mail
        if 'email' in gl:
            r = email.EmailReport( sender=gl['email']['sender'],
                                   to=str(job.email),
                                   subject="RNA-seq job "+str(job.description),
                                   smtp_server=gl['email']['smtp'] )
            r.appendBody('''Your RNA-seq job is finished.
                \n The description was: '''+str(job.description)+''' and its unique key is '''+opt.key+'''.
                \n You can retrieve the results at this url: '''+gl['hts_rnaseq']['url']+"jobs/"+opt.key+"/get_results" )
            r.send()

        sys.exit(0)
    except Usage, err:
        print >>sys.stderr, err.msg
        print >>sys.stderr, usage
        return 2


if __name__ == '__main__':
    sys.exit(main())





