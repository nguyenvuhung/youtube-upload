#!/usr/bin/python2
#
# Youtube-upload is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Youtube-upload is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Youtube-upload. If not, see <http://www.gnu.org/licenses/>.
#
# Author: Arnau Sanchez <tokland@gmail.com>
# Websites: http://code.google.com/p/youtube-upload
#           http://code.google.com/p/tokland/

"""
Upload videos to youtube from the command-line.

$ youtube-upload --email=myemail@gmail.com \ 
                 --password=mypassword \
                 --title="A.S. Mutter playing" \
                 --description="Anne Sophie Mutter plays Beethoven" \
                 --category=Music \
                 --keywords="mutter, beethoven" \
                 anne_sophie_mutter.flv
www.youtube.com/watch?v=pxzZ-fYjeYs
"""

import os
import re
import sys
import time
import string
import locale
import urllib
import optparse
import itertools
# python >= 2.6
from xml.etree import ElementTree 

# python-gdata (>= 1.2.4)
import gdata.media
import gdata.service
import gdata.geo
import gdata.youtube
import gdata.youtube.service

VERSION = "0.6.1"
DEVELOPER_KEY = "AI39si7iJ5TSVP3U_j4g3GGNZeI6uJl6oPLMxiyMst24zo1FEgnLzcG4i" + \
                "SE0t2pLvi-O03cW918xz9JFaf_Hn-XwRTTK7i1Img"

def debug(obj):
    """Write obj to standard error."""
    string = str(obj.encode(get_encoding(), "backslashreplace") 
                 if isinstance(obj, unicode) else obj)
    sys.stderr.write("--- " + string + "\n")
    
def get_encoding():
    """Guess terminal encoding.""" 
    return sys.stdout.encoding or locale.getpreferredencoding()

def compact(it):
    """Filter false (in the truth sense) elements in iterator."""
    return filter(bool, it)

def tosize(seq, size):
    """Return a list of fixed length from sequence (which may be shorter or longer)."""
    return (seq[:size] if len(seq) >= size else (seq + [None] * (size-len(seq))))        
    
def first(it):
    """Return first element in iterable."""
    return it.next()
    

class Youtube:
    """Interface the Youtube API."""        
    CATEGORIES_SCHEME = "http://gdata.youtube.com/schemas/2007/categories.cat"
    
    def __init__(self, developer_key, source="tokland-youtube_upload", 
                 client_id="tokland-youtube_upload"):
        """Login and preload available categories."""
        service = gdata.youtube.service.YouTubeService()
        service.ssl = False # SSL is not yet supported by Youtube API
        service.source = source
        service.developer_key = developer_key
        service.client_id = client_id        
        self.service = service
    
    def login(self, email, password, captcha_token=None, captcha_response=None):
        """Login into youtube."""
        self.service.email = email
        self.service.password = password
        self.service.ProgrammaticLogin(captcha_token, captcha_response)
        self.categories = self.get_categories()
        
    def get_upload_form_data(self, path, *args, **kwargs):
        """Return dict with keys 'post_url' and 'token' with upload info."""
        video_entry = self._create_video_entry(*args, **kwargs)
        post_url, token = self.service.GetFormUploadToken(video_entry)
        #debug("post url='%s', token='%s'" % (post_url, token))
        return dict(post_url=post_url, token=token)

    def upload_video(self, path, *args, **kwargs):
        """Upload a video."""
        video_entry = self._create_video_entry(*args, **kwargs)
        return self.service.InsertVideoEntry(video_entry, path)

    def create_playlist(self, title, description, private=False):
        """Create a new playlist and return its uri."""
        playlist = self.service.AddPlaylist(title, description, private)
        #playlist.GetFeedLink() return None. Why?
        return first(el.get("href") for el in playlist._ToElementTree() if "feedLink" in el.tag)

    def add_video_to_playlist(self, video_id, playlist_uri, title=None, description=None):
        """Add video to playlist."""
        playlist_video_entry = self.service.AddPlaylistVideoEntryToPlaylist(
            playlist_uri, video_id, title, description)
        return playlist_video_entry
      
    def check_upload_status(self, video_entry):
        """
        Check upload status of video entry.
        
        Return None if video is processed, and a pair (status, message) otherwise.
        """
        url, video_id = get_entry_info(video_entry)
        return self.service.CheckUploadStatus(video_id=video_id)
           
    def _create_video_entry(self, title, description, category, keywords=None, 
                            location=None, private=False):
        if category not in self.categories:
            valid = " ".join(self.categories.keys())
            raise ValueError("Invalid category '%s' (valid: %s)" % (category, valid))
        media_group = gdata.media.Group(
            title=gdata.media.Title(text=title),
            description=gdata.media.Description(description_type='plain', text=description),
            keywords=gdata.media.Keywords(text=keywords),
            category=gdata.media.Category(
                text=category,
                label=self.categories[category],
                scheme=self.CATEGORIES_SCHEME),
            private=(gdata.media.Private() if private else None),
            player=None)
        if location:            
            where = gdata.geo.Where()
            where.set_location(location)
        else: 
            where = None
        return gdata.youtube.YouTubeVideoEntry(media=media_group, geo=where)
                
    @classmethod
    def get_categories(cls):
        """Return categories dictionary with pairs (term, label)."""
        def get_pair(element):
            """Return pair (term, label) for a (non-deprecated) XML element."""
            if all(not(str(x.tag).endswith("deprecated")) for x in element.getchildren()):
                return (element.get("term"), element.get("label"))            
        xmldata = urllib.urlopen(cls.CATEGORIES_SCHEME).read()
        xml = ElementTree.XML(xmldata)
        return dict(compact(map(get_pair, xml)))


def get_entry_info(entry):      
    """Return pair (url, id) for video entry."""
    url = entry.GetHtmlLink().href.replace("&feature=youtube_gdata", "")
    video_id = re.search("=(.*)$", url).group(1)
    return url, video_id

def parse_location(string):
    """Return tuple (long, latitude) from string with coordinates."""
    if string and string.strip():
        return map(float, string.split(",", 1))

def wait_processing(yt, entry):
    debug("waiting until video is processed")
    while 1:
        try:
          response = yt.check_upload_status(entry)
        except socket.gaierror, msg:
          debug("network error (will retry): %s" % msg)
          continue                      
        if not response:
            debug("video is processed")
            break
        status, message = response
        debug("check_upload_status: %s" % " - ".join(compact(response)))
        if status != "processing":
            break 
        time.sleep(5)
    
def main_upload(arguments):
    """Upload video to Youtube."""
    usage = """Usage: %prog [OPTIONS] VIDEO_PATH ...

    Upload videos to youtube."""    
    parser = optparse.OptionParser(usage, version=VERSION)

    # Required options
    parser.add_option('-m', '--email', dest='email', type="string", 
      help='Authentication user email')
    parser.add_option('-p', '--password', dest='password', type="string", 
      help='Authentication user password')
    parser.add_option('-t', '--title', dest='title', type="string", 
      help='Video title')
    parser.add_option('-c', '--category', dest='category', type="string", 
      help='Video category')
      
    parser.add_option('-d', '--description', dest='description', type="string", 
        help='Video description')
    parser.add_option('', '--keywords', dest='keywords', type="string", 
        help='Video keywords (separated by commas: tag1,tag2,...)')
    parser.add_option('', '--title-template', dest='title_template', type="string",
        default="$title [$n/$total]", metavar="STRING", 
        help='Title template on multiple videos (default: $title [$n/$total])')
    
    parser.add_option('', '--get-categories', dest='get_categories',
        action="store_true", default=False, help='Show video categories')
    parser.add_option('', '--get-upload-form-info', dest='get_upload_form_data',
        action="store_true", default=False, help="Don't upload, just get the form info")
    parser.add_option('', '--private', dest='private',
        action="store_true", default=False, help='Set uploaded video as private')
    parser.add_option('', '--location', dest='location', type="string", default=None,
        metavar="LAT,LON", help='Video location (lat, lon). example: "43.3,5.42"')
    parser.add_option('', '--add-to-playlist', dest='add_to_playlist', type="string", default=None,
        metavar="URI", help='Add video(s) to an existing playlist')
    parser.add_option('', '--create-and-add-to-playlist', dest='create_playlist', type="string", 
        default=None, metavar="TITLE|DESCRIPTION|PRIVATE (0=no, 1=yes)", 
        help='Create new playlist and add uploaded video(s) to it')
    parser.add_option('', '--wait-processing', dest='wait_processing', action="store_true", 
        default=False, help='Wait until the video has been processed')
    # Captcha-related options          
    parser.add_option('', '--captcha-token', dest='captcha_token', type="string", 
      metavar="STRING", help='Captcha token')
    parser.add_option('', '--captcha-response', dest='captcha_response', type="string", 
      metavar="STRING", help='Captcha response')

    options, args = parser.parse_args(arguments)
    videos = args
    
    if options.get_categories:
        print " ".join(Youtube.get_categories().keys())
        return
    elif not args:
        parser.print_usage()
        return 1        
    required_options = ["email", "password", "title", "category"]
    missing = [opt for opt in required_options if not getattr(options, opt)]
    if missing:
        debug("Required option are missing: %s\n" % ", ".join(missing))
        parser.print_usage()
        return 1
    
    encoding = get_encoding()    
    password = (sys.stdin.readline().strip() if options.password == "-" else options.password)
    youtube = Youtube(DEVELOPER_KEY)    
    debug("Login to Youtube API: email='%s', password='%s'" % 
          (options.email, "*" * len(password)))
    try:
        youtube.login(options.email, password, captcha_token=options.captcha_token,
                      captcha_response=options.captcha_response)
    except gdata.service.CaptchaRequired:
        debug("We got a captcha request, look at this word image:\n%s" %
              youtube.service.captcha_url)
        debug("Now run the command adding these options (replace WORD with the actual captcha):\n" +
              "--captcha-token=%s --captcha-response=WORD" % youtube.service.captcha_token)
        return 2
    
    entries = []
    for index, video_path in enumerate(videos):
        namespace = dict(title=options.title, n=index+1, total=len(videos))
        complete_title = (string.Template(options.title_template).substitute(**namespace) 
                          if len(videos) > 1 else options.title)
        args = [video_path, complete_title, options.description, 
                options.category, options.keywords]
        kwargs = dict(private=options.private, location=parse_location(options.location))
        
        if options.get_upload_form_data:
            data = youtube.get_upload_form_data(*args, **kwargs)
            print "\n".join([video_path, data["token"], data["post_url"]])
        else:
            debug("Start video upload: %s (title: %s)" % (video_path, complete_title)) 
            entry = youtube.upload_video(*args, **kwargs)
            url, video_id = get_entry_info(entry)                
            if options.wait_processing:
                wait_processing(youtube, entry)
            sys.stdout.write(url + "\n")
            entries.append(entry)
                                       
    if entries and options.create_playlist:
        title, description, private = tosize(options.create_playlist.split("|", 2), 3)
        playlist_uri = youtube.create_playlist(title, description, (private == "1"))
        debug("Playlist created: %s" % playlist_uri)
        for entry in entries:
            video_id = get_entry_info(entry)[1]
            debug("Adding video (%s) to new playlist: %s" % (video_id, playlist_uri))
            youtube.add_video_to_playlist(video_id, playlist_uri)
    if options.add_to_playlist:
        for entry in entries:
            video_id = get_entry_info(entry)[1]
            debug("Adding video (%s) to existing playlist: %s" % (video_id, options.add_to_playlist))
            youtube.add_video_to_playlist(video_id, options.add_to_playlist)

if __name__ == '__main__':
    sys.exit(main_upload(sys.argv[1:]))
