package ch.epfl.bbcf.bbcfutils.access.gdv;

import java.io.IOException;

import ch.epfl.bbcf.bbcfutils.access.InternetConnection;



/**
 * Remote access on GDV
 * This class is intended to give feedbacks message to GDV
 * for the creation of tracks by the two daemons (transform_to_sqlite & compute_scores)
 * @author Yohan Jarosz
 *
 */
public class RemoteAccess {

	
	//ERRORS
	public static void sendTrackErrorMessage(String url,String message,String type,String trackId,String filePath) throws IOException{
		InternetConnection.sendPOSTConnection(
				url,"id=track_error&track_id="+trackId+"&file="+filePath+"&type="+type+"&mess="+message,InternetConnection.MIME_TYPE_FORM_APPLICATION);
	}

	public static void sendChromosomeErrorMessage(String url,String message,
			String type,String trackId, String nrAssemblyId) throws IOException {
		InternetConnection.sendPOSTConnection(
				url,"id=track_error&track_id="+trackId+"&type="+type+"&nrass="+nrAssemblyId+"&mess="+message,InternetConnection.MIME_TYPE_FORM_APPLICATION);
		
	}
	
	//SUCCEED
	public static void sendTrackSucceed(String url,String trackId, String database,
			String usermail, String type) throws IOException {
		System.out.println("post to :"+url);
		InternetConnection.sendPOSTConnection(
				url, "id=track_parsing_success&track_id="+trackId+"&db="+database+"&usermail="+usermail+"&type="+type,InternetConnection.MIME_TYPE_FORM_APPLICATION);
		
	}
}
