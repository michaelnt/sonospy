#!/usr/bin/env python

# movetags.py
#
# movetags.py copyright (c) 2010-2011 Mark Henkelis
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Mark Henkelis <mark.henkelis@tesco.net>

import os
import sys
import sqlite3
import optparse
import re
import time
import codecs
import ConfigParser
import datetime
from collections import defaultdict
from dateutil.parser import parse as parsedate
from scanfuncs import adjust_tracknumber, truncate_number
import filelog

import errors
errors.catch_errors()

MULTI_SEPARATOR = '\n'
enc = sys.getfilesystemencoding()
DEFAULTYEAR = 1
DEFAULTMONTH = 1
DEFAULTDAY = 1
DEFAULTDATE = datetime.datetime(DEFAULTYEAR, DEFAULTMONTH, DEFAULTDAY)

def process_tags(args, options, tagdatabase, trackdatabase):

    # tag_update records are processed sequentially as selected by id
    # only records that have changed will have a tag_update pair
    # each pair of tag_update records relate to a track record
    # each track record can result in album/artist/albumartist/composer and genre records
    # each track record can also result in lookup records for each of album/artist/albumartist/composer/genre
    # each track record can also result in work/virtual/tracknumber records
    # lookup records are maintained to reduce DB access for library operation on small machines
    # DB size is not constrained as the library is expected to have sufficient disk available
    # artist/albumartist/composer/genre are multi entry fields, so can result in multiple lookup records
    # lookup records are unique
    # state is not maintained across tag_update/track records to save memory - the db is checked for duplicates on insert

    logstring = "Processing tags"
    filelog.write_log(logstring)
    
    db2 = sqlite3.connect(trackdatabase)
    db2.execute("PRAGMA synchronous = 0;")
    cs2 = db2.cursor()

    if tagdatabase == trackdatabase:
        db1 = sqlite3.connect(tagdatabase)
        cs1 = db1.cursor()
        cs1.execute("attach '' as tempdb")
        cs1.execute("""create table tempdb.tags_update as select * from tags_update""")
        cs1.execute("""create table tempdb.tags as select * from tags""")
        cs1.execute("""create table tempdb.workvirtuals_update as select * from workvirtuals_update""")
    else:
        db1 = sqlite3.connect(tagdatabase)
        cs1 = db1.cursor()

#    artist_parentid = 100000000
#    album_parentid = 300000000
#    composer_parentid = 400000000
#    genre_parentid = 500000000
#    track_parentid = 600000000
#    playlist_parentid = 700000000

    # get ini settings
    config = ConfigParser.ConfigParser()
    config.optionxform = str
    config.read('scan.ini')

    # 'the' processing
    # command line overrides ini
    if options.the_processing:
        the_processing = options.the_processing.lower()
        logstring = "'The' processing: %s" % the_processing
        filelog.write_verbose_log(logstring)
    else:
        the_processing = 'remove'
        try:        
            the_processing = config.get('movetags', 'the_processing')
            the_processing = the_processing.lower()
        except ConfigParser.NoSectionError:
            pass
        except ConfigParser.NoOptionError:
            pass

    # multi-field separator
    multi_field_separator = ''
    try:        
        multi_field_separator = config.get('movetags', 'multiple_tag_separator')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass

    # multi-field inclusions
    include_artist = 'all'
    try:        
        include_artist = config.get('movetags', 'include_artist')
        include_artist = include_artist.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_artist in ['all', 'first', 'last']: include_artist = 'all'

    include_albumartist = 'all'
    try:        
        include_albumartist = config.get('movetags', 'include_albumartist')
        include_albumartist = include_albumartist.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_albumartist in ['all', 'first', 'last']: include_albumartist = 'all'
    
    include_composer = 'all'
    try:        
        include_composer = config.get('movetags', 'include_composer')
        include_composer = include_composer.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_composer in ['all', 'first', 'last']: include_composer = 'all'
    
    include_genre = 'all'
    try:        
        include_genre = config.get('movetags', 'include_genre')
        include_genre = include_genre.lower()
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    if not include_genre in ['all', 'first', 'last']: include_genre = 'all'

    # art preference
    prefer_folderart = False
    try:        
        prefer_folderart_option = config.get('movetags', 'prefer_folderart')
        if prefer_folderart_option.lower() == 'y':
            prefer_folderart = True
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    
    # names
    composer_album_work_name_structure = '"%s - %s - %s" % (genre, work, artist)'
    artist_album_work_name_structure = '"%s - %s - %s" % (composer, genre, work)'
    contributingartist_album_work_name_structure = '"%s - %s - %s" % (composer, genre, work)'
    work_name_structures = []
    try:        
        work_name_structures = config.items('work_name_structures')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    lookup_name_dict = {}
    work_name_dict = {}
    for k,v in work_name_structures:
        if k[0] == '_':
            lookup_name_dict[k] = v
        else:
            work_name_dict[k] = v
    composer_album_work = work_name_dict.get('COMPOSER_ALBUM', composer_album_work_name_structure)
    artist_album_work = work_name_dict.get('ARTIST_ALBUM', artist_album_work_name_structure)
    albumartist_album_work = artist_album_work
    contributingartist_album_work = work_name_dict.get('CONTRIBUTINGARTIST_ALBUM', contributingartist_album_work_name_structure)

    composer_album_virtual_name_structure = '"%s" % (virtual)'
    artist_album_virtual_name_structure = '"%s" % (virtual)'
    contributingartist_album_virtual_name_structure = '"%s" % (virtual)'
    virtual_name_structures = []
    try:        
        virtual_name_structures = config.items('virtual_name_structures')
    except ConfigParser.NoSectionError:
        pass
    except ConfigParser.NoOptionError:
        pass
    virtual_name_dict = {}
    for k,v in virtual_name_structures:
        if k[0] == '_':
            lookup_name_dict[k] = v
        else:
            virtual_name_dict[k] = v
    composer_album_virtual = virtual_name_dict.get('COMPOSER_ALBUM', composer_album_virtual_name_structure)
    artist_album_virtual = virtual_name_dict.get('ARTIST_ALBUM', artist_album_virtual_name_structure)
    albumartist_album_virtual = artist_album_virtual
    contributingartist_album_virtual = virtual_name_dict.get('CONTRIBUTINGARTIST_ALBUM', contributingartist_album_virtual_name_structure)

    # convert user defined fields and create old and new structures
    workstructurelist = [('composer_album_work', composer_album_work), ('artist_album_work', artist_album_work), ('albumartist_album_work', albumartist_album_work), ('contributingartist_album_work', contributingartist_album_work)]
    old_structures_work, new_structures_work = convertstructure(workstructurelist, lookup_name_dict)
    virtualstructurelist = [('composer_album_virtual', composer_album_virtual), ('artist_album_virtual', artist_album_virtual), ('albumartist_album_virtual', albumartist_album_virtual), ('contributingartist_album_virtual', contributingartist_album_virtual)]
    old_structures_virtual, new_structures_virtual = convertstructure(virtualstructurelist, lookup_name_dict)

    # get outstanding scan details
    db3 = sqlite3.connect(tagdatabase)
    cs3 = db3.cursor()
    try:
        cs3.execute("""select * from scans""")
    except sqlite3.Error, e:
        errorstring = "Error querying scan details: %s" % e.args[0]
        filelog.write_error(errorstring)

    #  buffer in memory
    scan_count = 0
    scan_details = []
    for srow in cs3:
        id, path = srow
        scan_details.append((id,path))
        scan_count += 1

    cs3.close()

    if options.scancount != None:
        logstring = "Scan count: %d" % options.scancount
        filelog.write_verbose_log(logstring)

    # process outstanding scans
    scan_count = 0
    last_scan_stamp = 0.0
    for scan_row in scan_details:

        scan_id, scan_path = scan_row
        scan_count += 1
        
        if options.scancount != None:   # need to be able to process zero
            if scan_count > options.scancount:
                break
        
        processing_count = 1

        try:

            logstring = "Processing tags from scan: %d" % scan_id
            filelog.write_verbose_log(logstring)

            # process tag records that exist for this scan
            if tagdatabase != trackdatabase:
                select_tu = 'tags_update'
                select_wv = 'workvirtuals_update'
                select_t  = 'tags'
            else:
                select_tu = 'tempdb.tags_update'
                select_wv = 'tempdb.workvirtuals_update'
                select_t  = 'tempdb.tags'
            if options.regenerate:
                orderby_tu = 'id, updateorder'
                orderby_wv = 'w.id, w.updateorder'
            else:
                orderby_tu = 'updatetype, rowid'
                orderby_wv = 'w.updatetype, w.rowid'

            # we need to process tags_updates followed by workvirtuals updates
            # 1) for tags we just select from tags_updates
            # 2) to get the full data for workvirtuals inserts/updates we join with tags (not tags_updates as it
            #    doesn't contain all the records we need (remember tags is the after image too))
            # 3) to get the full data for workvirtuals deletes we join with tags or tags_updates (if tag
            #    records have been deleted)
            # Note:
            #    In the SQL if we are processing a wv delete and the track exists in tags, it will be found in
            #    the second select (but not the third as it won't exist in tags_update). If the track does not 
            #    exist in tags then it must have been deleted and will exist in tags_update, so will be found
            #    in the third select (but not the second).
            # Note 2:
            #    The SQL assumes that the final result will conform to the three separate order by clauses
            statement = '''
                        select * from (
                            select *, '', 'album' from %s where scannumber=? order by %s
                        ) first

                        union all

                        select * from (
                            select t.id, t.id2,
                                    t.title, w.artist, w.title,
                                    w.genre, w.track, w.year,
                                    w.albumartist, w.composer, t.codec,
                                    t.length, t.size,
                                    w.created, t.path, t.filename,
                                    w.discnumber, t.comment, 
                                    t.folderart, t.trackart,
                                    t.bitrate, t.samplerate, 
                                    t.bitspersample, t.channels, t.mime,
                                    w.lastmodified,
                                    w.scannumber, t.folderartid, t.trackartid,
                                    w.inserted, w.lastscanned,
                                    w.updateorder, w.updatetype,
                                    t.album, w.type
                            from %s w, %s t
                            on t.id = w.id
                            where w.scannumber=?
                            order by %s
                        ) second

                        union all

                        select * from (
                            select t.id, t.id2,
                                    t.title, w.artist, w.title,
                                    w.genre, w.track, w.year,
                                    w.albumartist, w.composer, t.codec,
                                    t.length, t.size,
                                    w.created, t.path, t.filename,
                                    w.discnumber, t.comment, 
                                    t.folderart, t.trackart,
                                    t.bitrate, t.samplerate, 
                                    t.bitspersample, t.channels, t.mime,
                                    w.lastmodified,
                                    w.scannumber, t.folderartid, t.trackartid,
                                    w.inserted, w.lastscanned,
                                    w.updateorder, w.updatetype,
                                    t.album, w.type
                            from %s w inner join %s t
                            on t.id = w.id and t.updatetype = w.updatetype and t.updateorder = w.updateorder
                            where w.scannumber=?
                            and w.updatetype='D'
                            order by %s
                        ) third

                        ''' % (select_tu, orderby_tu, select_wv, select_t, orderby_wv, select_wv, select_tu, orderby_wv)
 
            cs1.execute(statement, (scan_id, scan_id, scan_id))

            for row0 in cs1:

                # get second record of pair
                row1 = cs1.fetchone()

                filelog.write_verbose_log(str(row0))
                filelog.write_verbose_log(str(row1))

                if not options.quiet and not options.verbose:
                    out = "processing tag: " + str(processing_count) + "\r" 
                    sys.stderr.write(out)
                    sys.stderr.flush()
                    processing_count += 1

                o_id, o_id2, o_title, o_artistliststring, o_album, o_genreliststring, o_tracknumber, o_year, o_albumartistliststring, o_composerliststring, o_codec, o_length, o_size, o_created, o_path, o_filename, o_discnumber, o_commentliststring, o_folderart, o_trackart, o_bitrate, o_samplerate, o_bitspersample, o_channels, o_mime, o_lastmodified, o_scannumber, o_folderartid, o_trackartid, o_inserted, o_lastscanned, o_updateorder, o_updatetype, o_originalalbum, o_albumtypestring = row0
                id, id2, title, artistliststring, album, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, scannumber, folderartid, trackartid, inserted, lastscanned, updateorder, updatetype, originalalbum, albumtypestring = row1
                o_filespec = os.path.join(o_path, o_filename)
                filespec = os.path.join(path, filename)

                # check that we do indeed have a pair
                if o_id != id:
                    # should only get here if we have a serious problem
                    errorstring = "tag/workvirtual update record pair does not match on ID"
                    filelog.write_error(errorstring)
                    continue

                # save latest scan time
                this_scan_stamp = lastscanned
                if float(this_scan_stamp) > last_scan_stamp:
                    last_scan_stamp = float(this_scan_stamp)

#                # default virtual albums and work to not being present
#                notfound = ''
#                o_work_entries = o_virtual_entries = []
#                work_entries = virtual_entries = []

                # update type shows how to process
                # if 'I' is a new file
                # elif 'U' contains updates from an existing file
                # elif 'D' is a deleted file

                o_genrelist = []
                o_artistlist = []
                o_albumartistlist = []
                o_composerlist = []

                if updatetype == 'D' or updatetype == 'U':
                
                    # separate out multi-entry lists
                    o_genreliststring, o_genrelist = unwrap_list(o_genreliststring, multi_field_separator, include_genre)
                    o_artistliststring, o_artistlist = unwrap_list(o_artistliststring, multi_field_separator, include_artist)
                    o_albumartistliststring, o_albumartistlist = unwrap_list(o_albumartistliststring, multi_field_separator, include_albumartist)
                    o_composerliststring, o_composerlist = unwrap_list(o_composerliststring, multi_field_separator, include_composer)
                        
                    # perform any "the" processing on artist/albumartist/composer lists
                    if the_processing == 'after' or the_processing == 'remove':
                        o_artistlist = process_list_the(o_artistlist, the_processing)
                        o_albumartistlist = process_list_the(o_albumartistlist, the_processing)
                        o_composerlist = process_list_the(o_composerlist, the_processing)

                    # adjust various fields
                    o_tracknumber = adjust_tracknumber(o_tracknumber)
                    o_year = adjust_year(o_year, o_filespec)
                    o_length = truncate_number(o_length)
                    o_size = truncate_number(o_size)
                    o_discnumber = truncate_number(o_discnumber)
                    o_bitrate = truncate_number(o_bitrate)
                    o_samplerate = truncate_number(o_samplerate)
                    o_bitspersample = truncate_number(o_bitspersample)
                    o_channels = truncate_number(o_channels)
                    o_folderartid = truncate_number(o_folderartid)
                    o_trackartid = truncate_number(o_trackartid)

                    # adjust albumartist - if there isn't one, copy in artist
                    if o_albumartistliststring == '':
                        o_albumartistliststring = o_artistliststring
                        o_albumartistlist = o_artistlist

#                    # create work and virtual entries if they exist
#                    o_work_entries, o_virtual_entries = getworkvirtualentries(o_commentliststring, o_tracknumber)

                genrelist = []
                artistlist = []
                albumartistlist = []
                composerlist = []

                if updatetype == 'I' or updatetype == 'U':

                    # separate out multi-entry lists
                    genreliststring, genrelist = unwrap_list(genreliststring, multi_field_separator, include_genre)
                    artistliststring, artistlist = unwrap_list(artistliststring, multi_field_separator, include_artist)
                    albumartistliststring, albumartistlist = unwrap_list(albumartistliststring, multi_field_separator, include_albumartist)
                    composerliststring, composerlist = unwrap_list(composerliststring, multi_field_separator, include_composer)
                        
                    # perform any "the" processing on artist/albumartist/composer lists
                    if the_processing == 'after' or the_processing == 'remove':
                        artistlist = process_list_the(artistlist, the_processing)
                        albumartistlist = process_list_the(albumartistlist, the_processing)
                        composerlist = process_list_the(composerlist, the_processing)

                    # adjust various fields
                    tracknumber = adjust_tracknumber(tracknumber)
                    year = adjust_year(year, filespec)
                    length = truncate_number(length)
                    size = truncate_number(size)
                    discnumber = truncate_number(discnumber)
                    bitrate = truncate_number(bitrate)
                    samplerate = truncate_number(samplerate)
                    bitspersample = truncate_number(bitspersample)
                    channels = truncate_number(channels)
                    folderartid = truncate_number(folderartid)
                    trackartid = truncate_number(trackartid)

                    # adjust albumartist - if there isn't one, copy in artist
                    if albumartistliststring == '':
                        albumartistliststring = artistliststring
                        albumartistlist = artistlist

#                    # create work and virtual entries if they exist
#                    work_entries, virtual_entries = getworkvirtualentries(commentliststring, tracknumber)

                # process track

                # don't process track table if work or virtual                
                if albumtypestring != 'album':

                    # for work/virtual need track id
                    try:
                        cs2.execute("""select rowid, id, duplicate from tracks where path=? and filename=?""",
                                    (o_path, o_filename))
                        row = cs2.fetchone()
                        if row:
                            track_rowid, track_id, o_duplicate = row
                            # duplicate won't exist in new data for an update, so force it
                            duplicate = o_duplicate
                    except sqlite3.Error, e:
                        errorstring = "Error getting track id: %s" % e.args[0]
                        filelog.write_error(errorstring)

                else:

                    # for update/delete need track id
                    if updatetype == 'D' or updatetype == 'U':
                        try:
                            cs2.execute("""select rowid, id, duplicate from tracks where path=? and filename=?""",
                                        (o_path, o_filename))
                            row = cs2.fetchone()
                            if row:
                                track_rowid, track_id, o_duplicate = row
                                # duplicate won't exist in new data for an update, so force it
                                duplicate = o_duplicate
                        except sqlite3.Error, e:
                            errorstring = "Error getting track id: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if updatetype == 'D':
                        try:
                            logstring = "DELETE TRACK: %s" % str(row0)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""delete from tracks where id=?""", (track_id,))
                        except sqlite3.Error, e:
                            errorstring = "Error deleting track details: %s" % e.args[0]
                            filelog.write_error(errorstring)
                    
                    elif updatetype == 'I':
                    
                        # new track, so insert
                        duplicate = 0   # used if a track is duplicated, for both the track and the album
                        try:
                            tracks = (id, id2, duplicate, title, artistliststring, album, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, '', '', lastscanned)
                            logstring = "INSERT TRACK: %s" % str(tracks)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into tracks values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tracks)
                            track_rowid = cs2.lastrowid
                        except sqlite3.Error, e:
                            # assume we have a duplicate
                            # Sonos doesn't like duplicate names, so append a number and keep trying
                            
                            # EXPERIMENTAL
                            
                            tstring = title + " (%"
                            try:
                                cs2.execute("""select max(duplicate) from tracks where title like ? and album=? and artist=? and tracknumber=?""",
                                            (tstring, album, artistliststring, tracknumber))
                                row = cs2.fetchone()
                            except sqlite3.Error, e:
                                errorstring = "Error finding max duplicate on track insert: %s" % e
                                filelog.write_error(errorstring)
                            if row:
                                tduplicate, = row
                                # special case for second entry - first won't have been matched
                                if not tduplicate:
                                    tcount = 2
                                else:
                                    tcount = int(tduplicate) + 1
                                tstring = title + " (" + str(tcount) + ")"            
                                tracks = (id, id2, tcount, tstring, artistliststring, album, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, '', '', lastscanned)
                                logstring = "INSERT TRACK: %s" % str(tracks)
                                filelog.write_verbose_log(logstring)
                                try:
                                    cs2.execute('insert into tracks values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tracks)
                                    track_rowid = cs2.lastrowid
                                    duplicate = tcount
                                except sqlite3.Error, e:
                                    errorstring = "Error performing duplicate processing on track insert: %s" % e
                                    filelog.write_error(errorstring)
                                    
                            '''                        
                            tcount = 2
                            while True:
                                tstring = title + " (" + str(tcount) + ")"            
                                tracks = (id, id2, tcount, tstring, artistliststring, album, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, path, filename, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, '', '', lastscanned)
                                logstring = "INSERT TRACK: %s" % str(tracks)
                                filelog.write_verbose_log(logstring)
                                try:
                                    cs2.execute('insert into tracks values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tracks)
                                    duplicate = tcount
                                    break
                                except sqlite3.Error, e:
                                    tcount += 1
                            '''

                            # EXPERIMENTAL

    #                    track_id = cs2.lastrowid
                        track_id = id

                    elif updatetype == 'U':
                        
                        # existing track, so update track with changes
                        try:
                            # recreate title if duplicate
                            if o_duplicate != 0:
                                title = title + " (" + str(o_duplicate) + ")"            

                            tracks = (id2, title, artistliststring, album, genreliststring, tracknumber, year, albumartistliststring, composerliststring, codec, length, size, created, discnumber, commentliststring, folderart, trackart, bitrate, samplerate, bitspersample, channels, mime, lastmodified, folderartid, trackartid, inserted, lastscanned, track_id)
                            logstring = "UPDATE TRACK: %s" % str(tracks)
                            filelog.write_verbose_log(logstring)
                            cs2.execute("""update tracks set 
                                           id2=?, title=?, artist=?, album=?, 
                                           genre=?, tracknumber=?, year=?, 
                                           albumartist=?, composer=?, codec=?, 
                                           length=?, size=?, 
                                           created=?, 
                                           discnumber=?, comment=?, 
                                           folderart=?, trackart=?,
                                           bitrate=?, samplerate=?, 
                                           bitspersample=?, channels=?, mime=?,
                                           lastmodified=?,
                                           folderartid=?, trackartid=?,
                                           inserted=?, lastscanned=? 
                                           where id=?""", 
                                           tracks)
                        except sqlite3.Error, e:
                            errorstring = "Error updating track details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # artist - one instance for all tracks from the album with the same artist/albumartist, with multi entry strings concatenated

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the album if nothing else refers to it
                # if we have an insert, insert the album if it doesn't already exist

                # for update/delete need artist id
                if updatetype == 'D' or updatetype == 'U':
                    try:
                        cs2.execute("""select id from artists where artist=? and albumartist=?""",
                                      (o_artistliststring, o_albumartistliststring))
                        row = cs2.fetchone()
                        if row:
                            artist_id, = row
                    except sqlite3.Error, e:
                        errorstring = "Error getting artist id: %s" % e.args[0]
                        filelog.write_error(errorstring)

                artist_change = False
                
                if updatetype == 'U':
                
                    # check whether artist/albumartist have changed
                    if o_artistliststring != artistliststring or o_albumartistliststring != albumartistliststring:
                        artist_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                if updatetype == 'D' or artist_change:

                    try:
                        # only delete artist if other tracks don't refer to it
                        delete = (o_artistliststring, o_albumartistliststring, artist_id)
                        logstring = "DELETE ARTIST: %s" % str(delete)
                        filelog.write_verbose_log(logstring)
                        cs2.execute("""delete from artists where not exists (select 1 from tracks where artist=? and albumartist=?) and id=?""", delete)
                    except sqlite3.Error, e:
                        errorstring = "Error deleting artist details: %s" % e.args[0]
                        filelog.write_error(errorstring)
                
                if updatetype == 'I' or artist_change:

                    if artist_change:
                        prev_artist_id = artist_id
                    try:

                        # check whether we already have this artist (from a previous run or another track)
                        count = 0
                        cs2.execute("""select id from artists where artist=? and albumartist=?""",
                                      (artistliststring, albumartistliststring))
                        crow = cs2.fetchone()
                        if crow:
                            artist_id, = crow
                            count = 1
                        if count == 0:
                            # insert base record
                            if artist_change:
#                                artist_id = prev_artist_id
                                artist_id = None
                            else:
                                artist_id = None
                            artists = (artist_id, artistliststring, albumartistliststring, '', '')
                            logstring = "INSERT ARTIST: %s" % str(artists)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into artists values (?,?,?,?,?)', artists)
                            artist_id = cs2.lastrowid

                    except sqlite3.Error, e:
                        errorstring = "Error inserting artist details: %s" % e.args[0]
                        filelog.write_error(errorstring)

                '''
                # create list of album names to process
                # Note:
                #     As the user can specify multiple work and virtual names per track, we don't
                #     necessarily have equal numbers of them in the old and new entries.
                #     To get around this we create individual old and new entries in the albumlist,
                #     and process the old ones as deletes and the new ones as inserts (so there are
                #     no updates).
                #     For normal albums, there will be a matching pair (unless it's an insert/delete),
                #     but we process those as a delete and an insert too for consistency.
                #
                '''
                
                # Note:
                #     work and virtual entries come in as separate rows
                #     there can be multiple work and virtual names per track
                
                
                # For normal albums we want to set the album details from the lowest track number.
                # Really we expect that to be 1, but it won't be if the album is incomplete
                # or the tracknumbers are blank.
                # We need to check tracks as they come in, storing details from successively lower
                # track numbers (only).
                # So that it is easier to reset album details from the next lowest track number
                # if the lowest is deleted, we store the track numbers we encounter and maintain
                # that list across deletes
                
                # For works and virtuals we use their tracknumber (which may be the original
                # tracknumber or a number set in the work/virtual data). We process those
                # tracknumbers as for albums
                
                albumlist = []
                structures = []

                if updatetype != 'I':
                    if albumtypestring == 'album':
                        albumlist.append((o_tracknumber, o_album, 0, albumtypestring, 'old'))
                    elif albumtypestring == 'work':
                        structures.append((old_structures_work, o_tracknumber, 'old'))
                        o_work = o_album
                    elif albumtypestring == 'virtual':
                        structures.append((old_structures_virtual, o_tracknumber, 'old'))
                        o_virtual = o_album
                if updatetype != 'D':
                    if albumtypestring == 'album':
                        albumlist.append((tracknumber, album, 0, albumtypestring, 'new'))
                    elif albumtypestring == 'work':
                        structures.append((new_structures_work, tracknumber, 'new'))
                        work = album
                    elif albumtypestring == 'virtual':
                        structures.append((new_structures_virtual, tracknumber, 'new'))
                        virtual = album

#                o_originalalbum = o_album
#                originalalbum = album

                if albumtypestring != 'album':

                    # this is a work or a virtual

                    # create combinaton lists
                    o_artistlisttmp = o_artistlist if o_artistlist != [] else ['']
                    artistlisttmp = artistlist if artistlist != [] else ['']
                    o_albumartistlisttmp = o_albumartistlist if o_albumartistlist != [] else ['']
                    albumartistlisttmp = albumartistlist if albumartistlist != [] else ['']
                    o_composerlisttmp = o_composerlist if o_composerlist != [] else ['']
                    composerlisttmp = composerlist if composerlist != [] else ['']
                    o_genrelisttmp = o_genrelist if o_genrelist != [] else ['']
                    genrelisttmp = genrelist if genrelist != [] else ['']

                    # create entries for each relevant structure
                    for structure, wvnumber, wvtype in structures:
                    
#                        print structure
#                        print wvnumber
#                        print wvtype
                    
                        for entry_string, entry_value in structure:

#                            print entry_string
#                            print entry_value

                            # process every combination (as we don't know what replacements are in the entry_string)
                            used = []
                            for o_artist in o_artistlisttmp:
                                for artist in artistlisttmp:
                                    for o_albumartist in o_albumartistlisttmp:
                                        for albumartist in albumartistlisttmp:
                                            for o_composer in o_composerlisttmp:
                                                for composer in composerlisttmp:
                                                    for o_genre in o_genrelisttmp:
                                                        for genre in genrelisttmp:
                                                            entry = eval(entry_string).strip()
                                                            entry_tuple = (wvnumber, entry, entry_value, albumtypestring, wvtype)
                                                            if entry_tuple not in used:
                                                                albumlist.append(entry_tuple)
                                                                used.append(entry_tuple)

#                # concatenate work and virtual entries
#                entries = []
#                for (number, string) in o_work_entries:
#                    entries.append((number, string, 'work', 'old'))
#                for (number, string) in o_virtual_entries:
#                    entries.append((number, string, 'virtual', 'old'))
#                for (number, string) in work_entries:
#                    entries.append((number, string, 'work', 'new'))
#                for (number, string) in virtual_entries:
#                    entries.append((number, string, 'virtual', 'new'))

#                # process work and virtual entries
#                for (number, string, wvtype, oldnew) in entries:

#                    # set relevant structure to use
#                    if oldnew == 'old' and wvtype == 'work':
#                        structures = old_structures_work
#                        o_work = string
#                    elif oldnew == 'old' and wvtype == 'virtual':
#                        structures = old_structures_virtual
#                        o_virtual = string
#                    elif oldnew == 'new' and wvtype == 'work':
#                        structures = new_structures_work
#                        work = string
#                    elif oldnew == 'new' and wvtype == 'virtual':
#                        structures = new_structures_virtual
#                        virtual = string




#need to make sure that old and new entries only contain the values from workvirtuals_update                    




                # set art at album level
                if folderart and folderart != '' or prefer_folderart:
                    cover = folderart
                    artid = folderartid
                elif trackart and trackart != '':
                    cover = trackart
                    artid = trackartid
                else:
                    cover = ''
                    artid = ''

#                print albumlist

                # process album names
                for (album_tracknumber, album_entry, albumvalue_entry, albumtype_entry, albumoldnew_entry) in albumlist:
                
                    if albumoldnew_entry == 'old':
                        o_album = album_entry
                        o_albumvalue = albumvalue_entry
                        o_albumtypevalue = translatealbumtype(albumtype_entry)
                        o_albumtype = (o_albumtypevalue * 10) + o_albumvalue
                        album_updatetype = 'D'
                    else:
                        album = album_entry
                        albumvalue = albumvalue_entry
                        albumtypevalue = translatealbumtype(albumtype_entry)
                        albumtype = (albumtypevalue * 10) + albumvalue
                        album_updatetype = 'I'
                    albumtypestring = albumtype_entry
                
                    # album - one instance for all tracks from the album with the same album/artist/albumartist/duplicate/albumtype, with multi entry strings concatenated

                    # if we have a delete, delete the album if nothing else refers to it
                    # if we have an insert, insert the album if it doesn't already exist

                    if album_updatetype == 'D':

                        # for delete need album id
                        album_id = None
                        try:
                            cs2.execute("""select id, tracknumbers from albums where album=? and artist=? and albumartist=? and duplicate=? and albumtype=?""",
                                        (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, o_albumtype))
                            row = cs2.fetchone()
                            if row:
                                album_id, tracknumbers = row
                                if albumtypestring == 'album' and updatetype == 'U':
                                    # need to maintain this across update (delete/insert) for album
                                    prev_album_id = album_id
                                
                        except sqlite3.Error, e:
                            errorstring = "Error getting album id: %s" % e.args[0]
                            filelog.write_error(errorstring)

                        if album_id:
                            # check whether we are deleting a track that is the track we got the album details for
                            s_tracks = tracknumbers.split(',')
                            if len(s_tracks) != 1:
                                # more that one track associated with this album
                                album_tracknumberstring = str(album_tracknumber)
                                if album_tracknumberstring.strip() == '': album_tracknumberstring = 'n'
                                if s_tracks[0] == album_tracknumberstring:
                                    # either we set the album from the track we are deleting
                                    # or there are no tracknumbers
                                    # - we need to set the album from the next track in the list
                                    s_tracks.pop(0)
                                    new_track = s_tracks[0]
                                    tracknumbers = ','.join(s_tracks)
                                    if new_track == 'n': find_track = ''
                                    else: find_track = int(new_track)
                                    try:
                                        cs2.execute("""select year, folderart, trackart, folderartid, trackartid, inserted, composer, created, lastmodified from tracks where album=? and artist=? and albumartist=? and duplicate=? and tracknumber=?""",
                                                    (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, find_track))
                                        row = cs2.fetchone()
                                        # TODO: check why we sometimes don't get a row
                                        if row:
                                            n_year, n_folderart, n_trackart, n_folderartid, n_trackartid, n_inserted, n_composer, n_created, n_lastmodified = row
                                        else:
                                            n_folderart = ''
                                            n_trackart = ''
                                            n_year = ''
                                            n_inserted = ''
                                            n_composer = ''
                                            n_created = ''
                                            n_lastmodified = ''

                                    except sqlite3.Error, e:
                                        errorstring = "Error getting track details: %s" % e.args[0]
                                        filelog.write_error(errorstring)

                                    # set art
                                    if n_folderart and n_folderart != '' or prefer_folderart:
                                        n_cover = n_folderart
                                        n_artid = n_folderartid
                                    elif n_trackart and n_trackart != '':
                                        n_cover = n_trackart
                                        n_artid = n_trackartid
                                    else:
                                        n_cover = ''
                                        n_artid = ''

                                    try:
                                        albums = (n_year, n_cover, n_artid, n_inserted, n_composer, tracknumbers, n_created, n_lastmodified, album_id)
                                        logstring = "UPDATE ALBUM: %s" % str(albums)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""update albums set 
                                                       year=?,
                                                       cover=?,
                                                       artid=?,
                                                       inserted=?,
                                                       composer=?,
                                                       tracknumbers=?,
                                                       created=?,
                                                       lastmodified=?
                                                       where id=?""", 
                                                       albums)
                                    except sqlite3.Error, e:
                                        errorstring = "Error resetting album details: %s" % e.args[0]
                                        filelog.write_error(errorstring)
                                
                                else:
                                    # we can just remove the track from the list and update the list
                                    s_tracks.remove(album_tracknumberstring)
                                    tracknumbers = ','.join(s_tracks)
                                    try:
                                        albums = (tracknumbers, album_id)
                                        logstring = "UPDATE ALBUM TRACKNUMBERS: %s" % str(albums)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute("""update albums set 
                                                       tracknumbers=?
                                                       where id=?""", 
                                                       albums)
                                    except sqlite3.Error, e:
                                        errorstring = "Error updating album tracknumbers: %s" % e.args[0]
                                        filelog.write_error(errorstring)

                            else:
                                # last track, can delete album                            
                                try:
                                    # only delete album if other tracks don't refer to it
                                    delete = (o_album, o_artistliststring, o_albumartistliststring, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE ALBUM: %s" % str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from albums where not exists (select 1 from tracks where album=? and artist=? and albumartist=? and duplicate=? and albumtype=?) and id=?""", delete)
                                except sqlite3.Error, e:
                                    errorstring = "Error deleting album details: %s" % e.args[0]
                                    filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            # check whether we already have this album (from a previous run or another track)
                            count = 0
                            cs2.execute("""select id, tracknumbers from albums where album=? and artist=? and albumartist=? and duplicate=? and albumtype=?""",
                                          (album, artistliststring, albumartistliststring, duplicate, albumtype))
                            crow = cs2.fetchone()
                            if crow:
                                album_id, tracknumbers = crow
                                count = 1
                                # now process the tracknumbers
                                s_tracks = tracknumbers.split(',')
                                tracks = [int(t) for t in s_tracks if t != 'n']
                                n_tracks = [t for t in s_tracks if t == 'n']
                                if not tracks: lowest_track = None
                                else: lowest_track = tracks[0]
                                if album_tracknumber != '':
                                    tracks.append(album_tracknumber)
                                    tracks.sort()
                                else:
                                    n_tracks.append('n')
                                s_tracks = [str(t) for t in tracks]
                                s_tracks.extend(n_tracks)
                                tracknumbers = ','.join(s_tracks)
                                # check whether the track we are processing has a lower number than the lowest one we have stored
                                if not lowest_track or album_tracknumber < lowest_track:
                                    albums = (album, artistliststring, year, albumartistliststring, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, album_id)
                                    logstring = "UPDATE ALBUM: %s" % str(albums)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""update albums set 
                                                   album=?,
                                                   artist=?,
                                                   year=?,
                                                   albumartist=?,
                                                   duplicate=?,
                                                   cover=?,
                                                   artid=?,
                                                   inserted=?,
                                                   composer=?,
                                                   tracknumbers=?,
                                                   created=?,
                                                   lastmodified=?,
                                                   albumtype=? 
                                                   where id=?""", 
                                                   albums)
                                else:
                                    # just store the tracknumber
                                    albums = (tracknumbers, album_id)
                                    logstring = "UPDATE ALBUM TRACKNUMBERS: %s" % str(albums)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""update albums set 
                                                   tracknumbers=?
                                                   where id=?""", 
                                                   albums)
                            if count == 0:
                                # insert base record
                                if albumtypestring == 'album' and updatetype == 'U':
#                                    album_id = prev_album_id
                                    album_id = None
                                else:
                                    album_id = None
                                tracknumbers = str(album_tracknumber)
                                if tracknumbers.strip() == '':
                                    tracknumbers = 'n'
                                albums = (album_id, album, artistliststring, year, albumartistliststring, duplicate, cover, artid, inserted, composerliststring, tracknumbers, created, lastmodified, albumtype, '', '')
                                logstring = "INSERT ALBUM: %s" % str(albums)
                                filelog.write_verbose_log(logstring)
                                cs2.execute('insert into albums values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', albums)
                                album_id = cs2.lastrowid

                        except sqlite3.Error, e:
                            errorstring = "Error inserting/updating album details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    # insert multiple entry lookups at album/track level if they don't already exist
                    # note that these can change by track, hence we do it outside of album (which may not change)

                    # if we have a delete, delete the lookup if nothing else refers to it
                    # if we have an insert, insert the lookup if it doesn't already exist
                    
                    if album_updatetype == 'D':

                        try:
                            # these lookups are unique on track id so nothing else refers to them (so just delete)
                            for o_genre in o_genrelist:
                                for o_artist in o_artistlist:
                                    delete = (track_rowid, o_genre, o_artist, o_album, o_duplicate, o_albumtype)
                                    logstring = "DELETE GenreArtistAlbumTrack: %s" % str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreArtistAlbumTrack where track_id=? and genre=? and artist=? and album=? and duplicate=? and albumtype=?""", delete)
                                for o_albumartist in o_albumartistlist:
                                    delete = (track_rowid, o_genre, o_albumartist, o_album, o_duplicate, o_albumtype)
                                    logstring = "DELETE GenreAlbumartistAlbumTrack: %s" % str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreAlbumartistAlbumTrack where track_id=? and genre=? and albumartist=? and album=? and duplicate=? and albumtype=?""", delete)
                            for o_artist in o_artistlist:
                                delete = (track_rowid, o_artist, o_album, o_duplicate, o_albumtype)
                                logstring = "DELETE ArtistAlbumTrack:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ArtistAlbumTrack where track_id=? and artist=? and album=? and duplicate=? and albumtype=?""", delete)
                            for o_albumartist in o_albumartistlist:
                                delete = (track_rowid, o_albumartist, o_album, o_duplicate, o_albumtype)
                                logstring = "DELETE AlbumartistAlbumTrack:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from AlbumartistAlbumTrack where track_id=? and albumartist=? and album=? and duplicate=? and albumtype=?""", delete)
                            for o_composer in o_composerlist:
                                delete = (track_rowid, o_composer, o_album, o_duplicate, o_albumtype)
                                logstring = "DELETE ComposerAlbumTrack:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ComposerAlbumTrack where track_id=? and composer=? and album=? and duplicate=? and albumtype=?""", delete)

                            if albumtypestring == 'work' or albumtypestring == 'virtual':
                                delete = (track_rowid, o_genreliststring, o_artistliststring, o_albumartistliststring, o_originalalbum, o_album, o_composerliststring, o_duplicate, o_albumtype, album_tracknumber)
                                logstring = "DELETE TrackNumbers:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from TrackNumbers where track_id=? and genre=? and artist=? and albumartist=? and album=? and dummyalbum=? and composer=? and duplicate=? and albumtype=? and tracknumber=?""", delete)

                        except sqlite3.Error, e:
                            errorstring = "Error deleting lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            for genre in genrelist:
                                for artist in artistlist:
                                    check = (track_rowid, genre, artist, album, duplicate, albumtype)
                                    cs2.execute("""select * from GenreArtistAlbumTrack where track_id=? and genre=? and artist=? and album=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check
                                        logstring = "INSERT GenreArtistAlbumTrack: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreArtistAlbumTrack values (?,?,?,?,?,?)', insert)
                                for albumartist in albumartistlist:
                                    check = (track_rowid, genre, albumartist, album, duplicate, albumtype)
                                    cs2.execute("""select * from GenreAlbumartistAlbumTrack where track_id=? and genre=? and albumartist=? and album=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check
                                        logstring = "INSERT GenreAlbumartistAlbumTrack: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreAlbumartistAlbumTrack values (?,?,?,?,?,?)', insert)
                            for artist in artistlist:
                                check = (track_rowid, artist, album, duplicate, albumtype)
                                cs2.execute("""select * from ArtistAlbumTrack where track_id=? and artist=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check
                                    logstring = "INSERT ArtistAlbumTrack:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ArtistAlbumTrack values (?,?,?,?,?)', insert)
                            for albumartist in albumartistlist:
                                check = (track_rowid, albumartist, album, duplicate, albumtype)
                                cs2.execute("""select * from AlbumartistAlbumTrack where track_id=? and albumartist=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check
                                    logstring = "INSERT AlbumartistAlbumTrack:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into AlbumartistAlbumTrack values (?,?,?,?,?)', insert)
                            for composer in composerlist:
                                check = (track_rowid, composer, album, duplicate, albumtype)
                                cs2.execute("""select * from ComposerAlbumTrack where track_id=? and composer=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check
                                    logstring = "INSERT ComposerAlbumTrack:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ComposerAlbumTrack values (?,?,?,?,?)', insert)

                            if albumtypestring == 'work' or albumtypestring == 'virtual':
                                check = (track_rowid, genreliststring, artistliststring, albumartistliststring, originalalbum, album, composerliststring, duplicate, albumtype, album_tracknumber)
                                cs2.execute("""select * from TrackNumbers where track_id=? and genre=? and artist=? and albumartist=? and album=? and dummyalbum=? and composer=? and duplicate=? and albumtype=? and tracknumber=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check
                                    logstring = "INSERT TrackNumbers:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into TrackNumbers values (?,?,?,?,?,?,?,?,?,?)', insert)

                        except sqlite3.Error, e:
                            errorstring = "Error inserting album/track lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    # insert multiple entry lookups at artist/album level if they don't already exist
                    # note that these can change by track, hence we do it outside of artist (which may not change)

                    # if we have a delete, delete the lookup if nothing else refers to it
                    # if we have an insert, insert the lookup if it doesn't already exist

                    if album_updatetype == 'D':

                        try:
                            for o_genre in o_genrelist:
                                for o_artist in o_artistlist:
                                    delete = (o_genre, o_artist, artist_id)
                                    logstring = "DELETE GenreArtist:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreArtist where not exists (select 1 from GenreArtistAlbum where genre=? and artist=?) and artist_id=?""", delete)
                                    delete = (o_genre, o_artist, o_album, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE GenreArtistAlbum:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreArtistAlbum where not exists (select 1 from GenreArtistAlbumTrack where genre=? and artist=? and album=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                                for o_albumartist in o_albumartistlist:
                                    delete = (o_genre, o_albumartist, artist_id)
                                    logstring = "DELETE GenreAlbumartist:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreAlbumartist where not exists (select 1 from GenreAlbumartistAlbum where genre=? and albumartist=?) and albumartist_id=?""", delete)
                                    delete = (o_genre, o_albumartist, o_album, o_duplicate, o_albumtype, album_id)
                                    logstring = "DELETE GenreAlbumartistAlbum:" + str(delete)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute("""delete from GenreAlbumartistAlbum where not exists (select 1 from GenreAlbumartistAlbumTrack where genre=? and albumartist=? and album=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                            for o_artist in o_artistlist:
                                delete = (o_artist, o_album, o_duplicate, o_albumtype, album_id)
                                logstring = "DELETE ArtistAlbum:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ArtistAlbum where not exists (select 1 from ArtistAlbumTrack where artist=? and album=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                            for o_albumartist in o_albumartistlist:
                                delete = (o_albumartist, o_album, o_duplicate, o_albumtype, album_id)
                                logstring = "DELETE AlbumartistAlbum:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from AlbumartistAlbum where not exists (select 1 from AlbumartistAlbumTrack where albumartist=? and album=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                            for o_composer in o_composerlist:
                                delete = (o_composer, o_album, o_duplicate, o_albumtype, album_id)
                                logstring = "DELETE ComposerAlbum:" + str(delete)
                                filelog.write_verbose_log(logstring)
                                cs2.execute("""delete from ComposerAlbum where not exists (select 1 from ComposerAlbumTrack where composer=? and album=? and duplicate=? and albumtype=?) and album_id=?""", delete)
                        except sqlite3.Error, e:
                            errorstring = "Error deleting (genre)/(artist/albumartist/composer)/artist lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                    if album_updatetype == 'I':

                        try:
                            for genre in genrelist:
                                for artist in artistlist:
                                    check = (artist_id, genre)
                                    cs2.execute("""select * from GenreArtist where artist_id=? and genre=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT GenreArtist: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreArtist values (?,?,?,?)', insert)
                                    check = (album_id, genre, artist, album, duplicate, albumtype)
                                    cs2.execute("""select * from GenreArtistAlbum where album_id=? and genre=? and artist=? and album=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT GenreArtistAlbum: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreArtistAlbum values (?,?,?,?,?,?,?,?)', insert)
                                for albumartist in albumartistlist:
                                    check = (artist_id, genre)
                                    cs2.execute("""select * from GenreAlbumartist where albumartist_id=? and genre=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT GenreAlbumartist: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreAlbumartist values (?,?,?,?)', insert)
                                    check = (album_id, genre, albumartist, album, duplicate, albumtype)
                                    cs2.execute("""select * from GenreAlbumartistAlbum where album_id=? and genre=? and albumartist=? and album=? and duplicate=? and albumtype=?""", check)
                                    crow = cs2.fetchone()
                                    if not crow:
                                        insert = check + ('', '')
                                        logstring = "INSERT GenreAlbumartistAlbum: %s" % str(insert)
                                        filelog.write_verbose_log(logstring)
                                        cs2.execute('insert into GenreAlbumartistAlbum values (?,?,?,?,?,?,?,?)', insert)
                            for artist in artistlist:
                                check = (album_id, artist, album, duplicate, albumtype)
                                cs2.execute("""select * from ArtistAlbum where album_id=? and artist=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check + ('', '')
                                    logstring = "INSERT ArtistAlbum:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ArtistAlbum values (?,?,?,?,?,?,?)', insert)
                            for albumartist in albumartistlist:
                                check = (album_id, albumartist, album, duplicate, albumtype)
                                cs2.execute("""select * from AlbumartistAlbum where album_id=? and albumartist=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check + ('', '')
                                    logstring = "INSERT AlbumartistAlbum:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into AlbumartistAlbum values (?,?,?,?,?,?,?)', insert)
                            for composer in composerlist:
                                check = (album_id, composer, album, duplicate, albumtype)
                                cs2.execute("""select * from ComposerAlbum where album_id=? and composer=? and album=? and duplicate=? and albumtype=?""", check)
                                crow = cs2.fetchone()
                                if not crow:
                                    insert = check + ('', '')
                                    logstring = "INSERT ComposerAlbum:" + str(insert)
                                    filelog.write_verbose_log(logstring)
                                    cs2.execute('insert into ComposerAlbum values (?,?,?,?,?,?,?)', insert)
                        except sqlite3.Error, e:
                            errorstring = "Error inserting (genre)/(artist/albumartist/composer)/album lookup details: %s" % e.args[0]
                            filelog.write_error(errorstring)

                # composer - one instance for all tracks from the album with the same composer, with multi entry strings concatenated

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the composer if nothing else refers to it
                # if we have an insert, insert the composer if it doesn't already exist

                # for update/delete need composer id
                if updatetype == 'D' or updatetype == 'U':
                    try:
                        cs2.execute("""select id from composers where composer=?""", (o_composerliststring,))
                        crow = cs2.fetchone()
                        if crow:
                            composer_id, = crow
                    except sqlite3.Error, e:
                        errorstring = "Error getting composer id: %s" % e.args[0]
                        filelog.write_error(errorstring)

                composer_change = False
                
                if updatetype == 'U':
                
                    # check whether composer has changed
                    if o_composerliststring != composerliststring:
                        composer_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                if updatetype == 'D' or composer_change:

                    try:
                        # only delete composer if other tracks don't refer to it
                        delete = (o_composerliststring, composer_id)
                        logstring = "DELETE COMPOSER: %s" % str(delete)
                        filelog.write_verbose_log(logstring)
                        cs2.execute("""delete from composers where not exists (select 1 from tracks where composer=?) and id=?""", delete)

                    except sqlite3.Error, e:
                        errorstring = "Error deleting composer details: %s" % e.args[0]
                        filelog.write_error(errorstring)
                
                if updatetype == 'I' or composer_change:

                    if composer_change:
                        prev_composer_id = composer_id
                    try:

                        # check whether we already have this composer (from a previous run or another track)
                        count = 0
                        cs2.execute("""select id from composers where composer=?""", (composerliststring,))
                        crow = cs2.fetchone()
                        if crow:
                            composer_id, = crow
                            count = 1
                        if count == 0:
                            # insert base record
                            if composer_change:
#                                composer_id = prev_composer_id
                                composer_id = None
                            else:
                                composer_id = None
                            composers = (composer_id, composerliststring, '', '')
                            logstring = "INSERT COMPOSER: %s" % str(composers)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into composers values (?,?,?,?)', composers)
                            composer_id = cs2.lastrowid

                    except sqlite3.Error, e:
                        errorstring = "Error inserting composer details: %s" % e.args[0]
                        filelog.write_error(errorstring)

                # genre - one instance for all tracks from the album with the same genre, with multi entry strings concatenated

                # if we have an update
                #     if the key fields have changed, process as a delete and an insert
                #     else update the non key fields if they have changed
                # if we have a delete, delete the genre if nothing else refers to it
                # if we have an insert, insert the genre if it doesn't already exist

                # for update/delete need genre id
                if updatetype == 'D' or updatetype == 'U':
                    try:
                        cs2.execute("""select id from genres where genre=?""", (o_genreliststring,))
                        crow = cs2.fetchone()
                        if crow:
                            genre_id, = crow
                    except sqlite3.Error, e:
                        errorstring = "Error getting genre id: %s" % e.args[0]
                        filelog.write_error(errorstring)

                genre_change = False
                
                if updatetype == 'U':
                
                    # check whether genre has changed
                    if o_genreliststring != genreliststring:
                        genre_change = True
                    else:
                        # there is nothing to change outside the keys fields
                        # so there can't be an update
                        pass

                if updatetype == 'D' or genre_change:

                    try:
                        # only delete genre if other tracks don't refer to it
                        delete = (o_genreliststring, genre_id)
                        logstring = "DELETE GENRE: %s" % str(delete)
                        filelog.write_verbose_log(logstring)
                        cs2.execute("""delete from genres where not exists (select 1 from tracks where genre=?) and id=?""", delete)

                    except sqlite3.Error, e:
                        errorstring = "Error getting genre details: %s" % e.args[0]
                        filelog.write_error(errorstring)
                
                if updatetype == 'I' or genre_change:

                    if genre_change:
                        prev_genre_id = genre_id
                    try:

                        # check whether we already have this genre (from a previous run or another track)
                        count = 0
                        cs2.execute("""select id from genres where genre=?""", (genreliststring,))
                        crow = cs2.fetchone()
                        if crow:
                            genre_id, = crow
                            count = 1
                        if count == 0:
                            # insert base record
                            if genre_change:
#                                genre_id = prev_genre_id
                                genre_id = None
                            else:
                                genre_id = None
                            genres = (genre_id, genreliststring, '', '')
                            logstring = "INSERT GENRE: %s" % str(genres)
                            filelog.write_verbose_log(logstring)
                            cs2.execute('insert into genres values (?,?,?,?)', genres)
                            genre_id = cs2.lastrowid
                    except sqlite3.Error, e:
                        errorstring = "Error inserting genre details: %s" % e.args[0]
                        filelog.write_error(errorstring)




            # post process playlist records to update track_id with rowid from tracks table
            try:
                cs2.execute("""update playlists set track_rowid = (select rowid from tracks where tracks.id = playlists.track_id)""")
                crow = cs2.fetchone()
            except sqlite3.Error, e:
                errorstring = "Error updating playlist ids: %s" % e.args[0]
                filelog.write_error(errorstring)



        except KeyboardInterrupt: 
            raise
#        except Exception, err: 
#            print str(err)

        logstring = "committing"
        filelog.write_verbose_log(logstring)
        db2.commit()

    cs1.close()

    # tidy up scan records
    scan_count = 0
    for scan_row in scan_details:
        scan_id, scan_path = scan_row
        scan_count += 1
        if options.scancount != None:   # need to be able to process zero
            if scan_count > options.scancount:
                break
        # remove the scan record and associated update records
        try:
            delete = (scan_id, scan_path)
            logstring = "DELETE SCAN: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from scans where id=? and scanpath=?""", delete)
            delete = (scan_id, )
            logstring = "DELETE TAGS UPDATES: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from tags_update where scannumber=?""", delete)
            logstring = "DELETE WORKVIRTUALS UPDATES: %s" % str(delete)
            filelog.write_verbose_log(logstring)
            cs2.execute("""delete from workvirtuals_update where scannumber=?""", delete)
        except sqlite3.Error, e:
            errorstring = "Error deleting scan/update details: %s" % e.args[0]
            filelog.write_error(errorstring)

    # update the container update ID
    if last_scan_stamp > 1:            
        try:
            params = (last_scan_stamp, scan_id)
            logstring = "UPDATE PARAMS: %s" % str(params)
            filelog.write_verbose_log(logstring)
            cs2.execute("""update params set
                           lastscanstamp=?, lastscanid=? 
                           where key='1'""", 
                           params)
        except sqlite3.Error, e:
            errorstring = "Error updating lastscanid details: %s" % e.args[0]
            filelog.write_error(errorstring)

    db2.commit()
    
    # update stats
    try:
        cs2.execute("""analyze""")
    except sqlite3.Error, e:
        errorstring = "Error updating stats: %s" % e.args[0]
        filelog.write_error(errorstring)

    db2.commit()
    
    cs2.close()

    logstring = "Tags processed"
    filelog.write_log(logstring)

    logstring = "finished"
    filelog.write_verbose_log(logstring)

def unwrap_list(liststring, multi_field_separator, include):
    # passed string can be multiple separator separated entries within multiple separator separated entries
    # e.g. 'artist1 \n artist2 ; artist3 \n artist4 ; artist5'
    #      separate artist tags separated by '\n' (MULTI_SEPARATOR)
    #      separate artists within a tag separated by ';' (multi_field_separator)
    # first split out separate tags
    multi = liststring.split(MULTI_SEPARATOR)
    # now split each tag
    if multi_field_separator == '':
        multilist = multi
    else:
        multilist = []
        for entry in multi:
            entrylist = re.split('[%s]' % multi_field_separator, entry)
            entrylist = [e.strip() for e in entrylist]
            entrylist = [e for e in entrylist if e != '']
            multilist.extend(entrylist)
    # select the entries we want
    if include == 'first': 
        newlist = [multilist[0]]
    elif include == 'last': 
        newlist [multilist[-1]]
    else: 
        newlist = multilist
    # recreate the original string with just the selected entries in
    newstring = MULTI_SEPARATOR.join(newlist)
    # return both the updated original string and the corresponding list
    return newstring, newlist
    
def process_list_the(plist, the_processing):
    newlist = []
    for entry in plist:
        if entry.lower().startswith("the ") and entry.lower() != "the the":
            postentry = entry[4:]
            if the_processing == 'after':
                preentry = entry[0:3]
                newentry = postentry + ", " + preentry
            else: # 'remove'
                newentry = postentry
            newlist.append(newentry)
        else:
            newlist.append(entry)
    return newlist

def adjust_year(year, filespec):
    # convert year to ordinal date
    ordinal = None
    try:
        yeardatetime = parsedate(year, default=DEFAULTDATE)
        if yeardatetime.year != 1:
            ordinal = yeardatetime.toordinal()
    except Exception:
        # don't really care why parsedate failed
        # have another go at finding the century
        cccc = None
        datefacets = re.split('\D', year)
        for i in range(len(datefacets), 0, -1):
            chars = datefacets[i-1]
            if len(chars) == 4:
                cccc = int(chars)
                break
        if not cccc:
            warningstring = "Warning processing track: %s : tag: %s : %s" % (filespec, year, "Couldn't convert year tag to cccc, year tag ignored")
            filelog.write_warning(warningstring)
        else:
            yeardate = datetime.date(cccc, DEFAULTMONTH, DEFAULTDAY)
            ordinal = yeardate.toordinal()
    return ordinal

def splitworkvirtual(workstring):
    workstring = workstring.strip()
    worknumber = None
    if workstring != '':
        try:
            worknumberstring = re.split('\D', workstring)[0]
            if worknumberstring != '' and workstring[len(worknumberstring):len(worknumberstring)+1] == ',':
                workstring = workstring[len(worknumberstring)+1:]
                worknumber = int(worknumberstring)
        except ValueError:
            pass
        except AttributeError:
            pass
    if workstring == '':
        workstring = None
    return worknumber, workstring

work_sep = 'work='
virtual_sep = 'virtual='
wv_sep = '(%s|%s)' % (work_sep, virtual_sep)

'''
def getworkvirtualentries(liststring, tracknumber):
    work_strings = []
    virtual_strings = []
    lines = liststring.split('\n')
    for line in lines:
        words = re.split(wv_sep, line)
        for i in range(1, len(words)):
            if words[i] == work_sep and words[i+1] != '':
                number, string = splitworkvirtual(words[i+1])
                if not number:
                    number = tracknumber
                work_strings.append((number, string))
            if words[i] == virtual_sep and words[i+1] != '':
                number, string = splitworkvirtual(words[i+1])
                if not number:
                    number = tracknumber
                virtual_strings.append((number, string))
    return work_strings, virtual_strings        
'''

def translatealbumtype(albumtype):
    if albumtype == 'album':
        return 1
    elif albumtype == 'virtual':
        return 2
    elif albumtype == 'work':
        return 3

def translatestructuretype(structuretype):
    if structuretype == 'composer_album_work':
        return 1
    elif structuretype == 'artist_album_work':
        return 2
    elif structuretype == 'albumartist_album_work':
        return 3
    elif structuretype == 'contributingartist_album_work':
        return 4
    elif structuretype == 'composer_album_virtual':
        return 5
    elif structuretype == 'artist_album_virtual':
        return 6
    elif structuretype == 'albumartist_album_virtual':
        return 7
    elif structuretype == 'contributingartist_album_virtual':
        return 8

def convertstructure(structurelist, lookup_name_dict):
    old_structures = []
    new_structures = []
    for name, structure in structurelist:
        namevalue = translatestructuretype(name)
        field_sep_pos = structure.rfind('(')
        field_string = structure[:field_sep_pos]
        fields = structure[field_sep_pos+1:]
        fields = fields[:fields.rfind(')')]
        fields = fields.split(',')
        old_fields = []
        new_fields = []
        for field in fields:
            field = field.strip()
            if field[0] == '_':
                field_transform = lookup_name_dict.get(field, None)
                if field_transform:        
                    field = field_transform
            # assume fieldname is first part of user defined field
            subfields = field.split('.')
            firstfield = subfields[0]
            restoffield = field[len(firstfield):]
            oldfield = convertfieldname(firstfield, 'old') + restoffield
            newfield = convertfieldname(firstfield, 'new') + restoffield
            old_fields.append(oldfield)
            new_fields.append(newfield)
        # recreate format strings
        fields = ','.join(old_fields)
        old_structures.append(('%s (%s)' % (field_string, fields), namevalue))
        fields = ','.join(new_fields)
        new_structures.append(('%s (%s)' % (field_string, fields), namevalue))
    return old_structures, new_structures

# convert field names
field_conversions = {
                    'work':'work',                          # dummy, not DB field
                    'virtual':'virtual',                    # dummy, not DB field
                    'id':'id', 
#                    'artist':'artistliststring', 
                    'artist':'artist', 
                    'album':'album', 
#                    'genre':'genreliststring', 
                    'genre':'genre', 
                    'tracknumber':'tracknumber', 
                    'year':'year', 
#                    'albumartist':'albumartistliststring', 
                    'albumartist':'albumartist', 
#                    'composer':'composerliststring', 
                    'composer':'composer', 
                    'created':'created', 
                    'lastmodified':'lastmodified', 
                    'inserted':'inserted'
                    }

def convertfieldname(fieldname, converttype):
    if fieldname in field_conversions:
        convertedfield = field_conversions[fieldname]
    else:
        convertedfield = 'notfound'

    if converttype == 'old':
        return "o_" + convertedfield
    else:
        return convertedfield

def check_target_database_exists(database):
    ''' 
        create database if it doesn't already exist
        if it exists, create tables if they don't exist
        return abs path
    '''
    create_database(database)

def create_database(database):
    db = sqlite3.connect(database)
    c = db.cursor()
    try:
        # master parameters
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="params"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table params (key text,
                                              lastmodified real, 
                                              lastscanstamp real, 
                                              lastscanid integer, 
                                              use_albumartist text,
                                              show_duplicates text,
                                              album_identification text)
                      ''')
            c.execute('''insert into params values ('1', 0, 0, ' ', '', '', '')''')

        # sort parameters
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="sorts"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table sorts (proxyname text,
                                             controller text,
                                             sort_type text,
                                             sort_seq integer,
                                             sort_order text,
                                             sort_prefix text,
                                             sort_suffix text,
                                             album_type text,
                                             header_name text,
                                             active text)
                      ''')

            c.executescript('''
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'GENRE', '', '', '', '', '', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'GENRE_ARTIST', '', '', '', 'playcount', '', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST', '', '', '', 'playcount', '', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'CONTRIBUTINGARTIST', '', '', '', 'playcount', '', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER', '', '', '', 'playcount', '', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'PCDCR', 'ALBUM', '', 'created desc', '', 'albumartist', 'album,albumartist_virtual', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'CR200', 'ALBUM', '', 'created desc', '', '', 'album,albumartist_virtual', '', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST_ALBUM', '1', 'album', '', '', 'work', 'work, by name', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST_ALBUM', '2', 'album', '', 'playcount', 'virtual', 'virtual, by name', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST_ALBUM', '3', 'lastplayed', '', 'playcount', '', 'by date last played (asc)', '');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST_ALBUM', '4', 'year', 'year', 'playcount', '', 'by year released', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'ARTIST_ALBUM', '5', 'created desc', '', 'playcount', '', 'by date added (desc)', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'CONTRIBUTINGARTIST_ALBUM', '1', 'lastplayed', '', 'playcount', '', 'by date last played (asc)', '');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'CONTRIBUTINGARTIST_ALBUM', '2', 'year', 'year', 'playcount', '', 'by year released', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'CONTRIBUTINGARTIST_ALBUM', '3', 'created desc', '', 'playcount', '', 'by date added (desc)', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER_ALBUM', '1', 'album', '', '', 'work', 'work, by work name', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER_ALBUM', '2', 'album', '', 'playcount', 'virtual', 'virtual, by artist', 'Y');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER_ALBUM', '3', 'lastplayed', '', 'playcount', '', 'by date last played (asc)', '');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER_ALBUM', '4', 'created desc', '', 'playcount', '', 'by date added (desc)', '');
INSERT INTO sorts (proxyname, controller, sort_type, sort_seq, sort_order, sort_prefix, sort_suffix, album_type, header_name, active) VALUES ('ALL', 'ALL', 'COMPOSER_ALBUM', '5', 'albumartist', 'albumartist', '', '', 'by artist', 'Y');
                      ''')

        # tracks - contain all detail from tags
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="tracks"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table tracks (id text, 
                                              id2 text,
                                              duplicate integer,
                                              title text COLLATE NOCASE, 
                                              artist text COLLATE NOCASE, 
                                              album text COLLATE NOCASE,
                                              genre text COLLATE NOCASE, 
                                              tracknumber integer,
                                              year integer,
                                              albumartist text COLLATE NOCASE, 
                                              composer text COLLATE NOCASE, 
                                              codec text,
                                              length integer, 
                                              size integer,
                                              created real, 
                                              path text, 
                                              filename text,
                                              discnumber integer, 
                                              comment text, 
                                              folderart text,
                                              trackart text,
                                              bitrate integer, 
                                              samplerate integer, 
                                              bitspersample integer,
                                              channels integer, 
                                              mime text,
                                              lastmodified real, 
                                              folderartid integer,
                                              trackartid integer,
                                              inserted real,
                                              lastplayed real,
                                              playcount integer,
                                              lastscanned real)
                      ''')
            c.execute('''create unique index inxTracks on tracks (title, album, artist, tracknumber)''')
            c.execute('''create unique index inxTrackId on tracks (id)''')
            c.execute('''create index inxTrackId2 on tracks (id2)''')
            c.execute('''create index inxTrackDuplicates on tracks (duplicate)''')
            c.execute('''create index inxTrackTitles on tracks (title)''')
            c.execute('''create index inxTrackAlbums on tracks (album)''')
            c.execute('''create index inxTrackAlbumDups on tracks (album, duplicate)''')
#            c.execute('''create index inxTrackAlbumDupTrackTitles on tracks (album, duplicate, tracknumber, title)''')

            c.execute('''create index inxTrackAlbumDiscTrackTitles on tracks (album, discnumber, tracknumber, title)''')
            c.execute('''create index inxTrackDiscTrackTitles on tracks (discnumber, tracknumber, title)''')
            c.execute('''create index inxTrackArtists on tracks (artist)''')
            c.execute('''create index inxTrackAlbumArtists on tracks (albumartist)''')
            c.execute('''create index inxTrackComposers on tracks (composer)''')
            c.execute('''create index inxTrackYears on tracks (year)''')
            c.execute('''create index inxTrackInserteds on tracks (inserted)''')
            c.execute('''create index inxTrackTracknumber on tracks (tracknumber)''')
            c.execute('''create index inxTrackLastplayeds on tracks (lastplayed)''')
            c.execute('''create index inxTrackPlaycounts on tracks (playcount)''')
            c.execute('''create index inxTrackPathFilename on tracks (path, filename)''')
            c.execute('''create index inxTrackPlay on tracks (title, album, artist, length)''')

        # albums - one entry for each unique album/artist/albumartist combination from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="albums"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table albums (id integer primary key autoincrement, 
                                              album text COLLATE NOCASE, 
                                              artist text COLLATE NOCASE,
                                              year integer,
                                              albumartist text COLLATE NOCASE, 
                                              duplicate integer,
                                              cover text,
                                              artid integer,
                                              inserted real,
                                              composer text COLLATE NOCASE,
                                              tracknumbers text,
                                              created real,
                                              lastmodified real,
                                              albumtype integer, 
                                              lastplayed real,
                                              playcount integer)
                      ''')
            c.execute('''create unique index inxAlbums on albums (album, artist, albumartist, duplicate, albumtype)''')
            c.execute('''create unique index inxAlbumId on albums (id)''')
            c.execute('''create index inxAlbumAlbums on albums (album)''')
            c.execute('''create index inxAlbumArtists on albums (artist)''')
            c.execute('''create index inxAlbumAlbumartists on albums (albumartist)''')
            c.execute('''create index inxAlbumComposers on albums (composer)''')
            c.execute('''create index inxAlbumYears on albums (year)''')
            c.execute('''create index inxAlbumInserteds on albums (inserted)''')
            c.execute('''create index inxAlbumcreateds on albums (created)''')
            c.execute('''create index inxAlbumlastmodifieds on albums (lastmodified)''')
            c.execute('''create index inxAlbumLastPlayeds on albums (lastplayed)''')
            c.execute('''create index inxAlbumPlaycounts on albums (playcount)''')



            c.execute('''create index inxAlbumTracknumbers on albums (tracknumbers)''')
            c.execute('''create index inxAlbumTracknumbers2 on albums (album, tracknumbers, albumtype, duplicate)''')
           

            
            # seed autoincrement
            c.execute('''insert into albums values (300000000,'','','','','','','','','','','','','','','')''')
            c.execute('''delete from albums where id=300000000''')

        # artists - one entry for each unique artist/albumartist combination from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="artists"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table artists (id integer primary key autoincrement,
                                               artist text COLLATE NOCASE,
                                               albumartist text COLLATE NOCASE, 
                                               lastplayed real,
                                               playcount integer)
                      ''')
            c.execute('''create unique index inxArtists on artists (artist, albumartist)''')
            c.execute('''create unique index inxArtistId on artists (id)''')
            c.execute('''create index inxArtistArtists on artists (artist)''')
            c.execute('''create index inxArtistAlbumArtists on artists (albumartist)''')
            c.execute('''create index inxArtistLastplayeds on artists (lastplayed)''')
            c.execute('''create index inxArtistPlaycounts on artists (playcount)''')
            # seed autoincrement
            c.execute('''insert into artists values (100000000,'','','','')''')
            c.execute('''delete from artists where id=100000000''')

        # composers - one entry for each unique composer from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="composers"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table composers (id integer primary key autoincrement,
                                                 composer text COLLATE NOCASE,
                                                 lastplayed real,
                                                 playcount integer)
                      ''')
            c.execute('''create unique index inxComposers on composers (composer)''')
            c.execute('''create unique index inxComposerId on composers (id)''')
            c.execute('''create index inxComposerLastplayeds on composers (lastplayed)''')
            c.execute('''create index inxComposerPlaycounts on composers (playcount)''')
            # seed autoincrement
            c.execute('''insert into composers values (400000000,'','','')''')
            c.execute('''delete from composers where id=400000000''')

        # genres - one entry for each unique genre from tracks list
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="genres"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table genres (id integer primary key autoincrement,
                                              genre text COLLATE NOCASE,
                                              lastplayed real,
                                              playcount integer)
                      ''')
            c.execute('''create unique index inxGenres on genres (genre)''')
            c.execute('''create unique index inxGenreId on genres (id)''')
            c.execute('''create index inxGenreLastplayeds on genres (lastplayed)''')
            c.execute('''create index inxGenrePlaycounts on genres (playcount)''')
            # seed autoincrement
            c.execute('''insert into genres values (500000000,'','','')''')
            c.execute('''delete from genres where id=500000000''')
            
        # playlists
#        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="playlists"')
#        n, = c.fetchone()
#        if n == 0:
#            c.execute('''create table playlists (id integer primary key autoincrement,
#                                                 playlist text COLLATE NOCASE,
#                                                 path text)
#                      ''')
#            c.execute('''create unique index inxPlaylists on playlists (playlist)''')
#            c.execute('''create unique index inxPlaylistId on playlists (id)''')
#            # seed autoincrement
#            c.execute('''insert into playlists values (700000000,'','')''')
#            c.execute('''delete from playlists where id=700000000''')
            
        # multi entry fields lookups - genre/artist level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtist (artist_id integer, genre text COLLATE NOCASE, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxGenreArtist on GenreArtist (artist_id, genre)''')
            c.execute('''create index inxGenreArtistGenre on GenreArtist (genre)''')
            c.execute('''create index inxGenreArtistLastplayed on GenreArtist (lastplayed)''')
            c.execute('''create index inxGenreArtistPlaycount on GenreArtist (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartist"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartist (albumartist_id integer, genre text COLLATE NOCASE, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxGenreAlbumartist on GenreAlbumartist (albumartist_id, genre)''')
            c.execute('''create index inxGenreAlbumartistGenre on GenreAlbumartist (genre)''')
            c.execute('''create index inxGenreAlbumartistLastplayed on GenreAlbumartist (lastplayed)''')
            c.execute('''create index inxGenreAlbumartistPlaycount on GenreAlbumartist (playcount)''')

        # multi entry fields lookups - composer and artist/album level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtistAlbum (album_id integer, genre text COLLATE NOCASE, artist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxGenreArtistAlbum on GenreArtistAlbum (album_id, genre, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumGenreArtist on GenreArtistAlbum (genre, artist, album, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumArtist on GenreArtistAlbum (artist)''')
            c.execute('''create index inxGenreArtistAlbumLastplayed on GenreArtistAlbum (lastplayed)''')
            c.execute('''create index inxGenreArtistAlbumPlaycount on GenreArtistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartistAlbum (album_id integer, genre text COLLATE NOCASE, albumartist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxGenreAlbumartistAlbum on GenreAlbumartistAlbum (album_id, genre, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumGenreAlbumartist on GenreAlbumartistAlbum (genre, albumartist, album, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumAlbumartist on GenreAlbumartistAlbum (albumartist)''')
            c.execute('''create index inxGenreAlbumartistAlbumLastplayed on GenreAlbumartistAlbum (lastplayed)''')
            c.execute('''create index inxGenreAlbumartistAlbumPlaycount on GenreAlbumartistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ArtistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ArtistAlbum (album_id integer, artist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxArtistAlbum on ArtistAlbum (album_id, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxArtistAlbumArtist on ArtistAlbum (artist)''')
            c.execute('''create index inxArtistAlbumArtistType on ArtistAlbum (artist, albumtype)''')
            c.execute('''create index inxArtistAlbumLastplayed on ArtistAlbum (lastplayed)''')
            c.execute('''create index inxArtistAlbumPlaycount on ArtistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="AlbumartistAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table AlbumartistAlbum (album_id integer, albumartist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxAlbumartistAlbum on AlbumartistAlbum (album_id, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxAlbumartistAlbumAlbumartist on AlbumartistAlbum (albumartist)''')
            c.execute('''create index inxAlbumartistAlbumAlbumartistType on AlbumartistAlbum (albumartist, albumtype)''')
            c.execute('''create index inxAlbumartistAlbumLastplayed on AlbumartistAlbum (lastplayed)''')
            c.execute('''create index inxAlbumartistAlbumPlaycount on AlbumartistAlbum (playcount)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ComposerAlbum"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ComposerAlbum (album_id integer, composer text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer, lastplayed real, playcount integer)''')
            c.execute('''create unique index inxComposerAlbum on ComposerAlbum (album_id, composer, album, duplicate, albumtype)''')
            c.execute('''create index inxComposerAlbumComposer on ComposerAlbum (composer)''')
            c.execute('''create index inxComposerAlbumComposerType on ComposerAlbum (composer, albumtype)''')
            c.execute('''create index inxComposerAlbumAlbum on ComposerAlbum (album)''')
            c.execute('''create index inxComposerAlbumLastplayed on ComposerAlbum (lastplayed)''')
            c.execute('''create index inxComposerAlbumPlaycount on ComposerAlbum (playcount)''')

        # multi entry fields lookups - album/track level
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreArtistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreArtistAlbumTrack (track_id integer, genre text COLLATE NOCASE, artist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer)''')
            c.execute('''create unique index inxGenreArtistAlbumTrack on GenreArtistAlbumTrack (track_id, genre, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumTrackGenreArtistAlbum on GenreArtistAlbumTrack (genre, artist, album, albumtype)''')
            c.execute('''create index inxGenreArtistAlbumTrackGenreArtistAlbumDup on GenreArtistAlbumTrack (genre, artist, album, duplicate)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="GenreAlbumartistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table GenreAlbumartistAlbumTrack (track_id integer, genre text COLLATE NOCASE, albumartist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer)''')
            c.execute('''create unique index inxGenreAlbumartistAlbumTrack on GenreAlbumartistAlbumTrack (track_id, genre, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumTrackGenreAlbumArtistAlbum on GenreAlbumartistAlbumTrack (genre, albumartist, album, albumtype)''')
            c.execute('''create index inxGenreAlbumartistAlbumTrackGenreAlbumArtistAlbumDup on GenreAlbumartistAlbumTrack (genre, albumartist, album, duplicate)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ArtistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ArtistAlbumTrack (track_id integer, artist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer)''')
            c.execute('''create unique index inxArtistAlbumTrack on ArtistAlbumTrack (track_id, artist, album, duplicate, albumtype)''')
            c.execute('''create index inxArtistAlbumTrackArtistAlbum on ArtistAlbumTrack (artist, album, albumtype)''')
            c.execute('''create index inxArtistAlbumTrackArtistAlbumDup on ArtistAlbumTrack (artist, album, duplicate, albumtype)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="AlbumartistAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table AlbumartistAlbumTrack (track_id integer, albumartist text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer)''')
            c.execute('''create unique index inxAlbumArtistAlbumTrack on AlbumartistAlbumTrack (track_id, albumartist, album, duplicate, albumtype)''')
            c.execute('''create index inxAlbumArtistAlbumTrackAlbumArtistAlbum on AlbumartistAlbumTrack (albumartist, album, albumtype)''')
            c.execute('''create index inxAlbumArtistAlbumTrackAlbumArtistAlbumDup on AlbumartistAlbumTrack (albumartist, album, duplicate, albumtype)''')

        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="ComposerAlbumTrack"')
        n, = c.fetchone()
        if n == 0:
            c.execute('''create table ComposerAlbumTrack (track_id integer, composer text COLLATE NOCASE, album text COLLATE NOCASE, duplicate integer, albumtype integer)''')
            c.execute('''create unique index inxComposerAlbumTrack on ComposerAlbumTrack (track_id, composer, album, duplicate, albumtype)''')
            c.execute('''create index inxComposerAlbumTrackComposerAlbum on ComposerAlbumTrack (composer, album, albumtype)''')
            c.execute('''create index inxComposerAlbumTrackComposerAlbumDup on ComposerAlbumTrack (composer, album, duplicate, albumtype)''')

        # work/virtual track number lookup
        c.execute('SELECT count(*) FROM sqlite_master WHERE type="table" AND name="TrackNumbers"')
        n, = c.fetchone()
        if n == 0:
            # TODO: check these indexes
            c.execute('''create table TrackNumbers (track_id integer, 
                                                    genre text COLLATE NOCASE, 
                                                    artist text COLLATE NOCASE, 
                                                    albumartist text COLLATE NOCASE, 
                                                    album text COLLATE NOCASE, 
                                                    dummyalbum text COLLATE NOCASE, 
                                                    composer text COLLATE NOCASE, 
                                                    duplicate integer, 
                                                    albumtype integer, 
                                                    tracknumber integer)''')
            c.execute('''create unique index inxTrackNumbers on TrackNumbers (track_id, genre, artist, albumartist, album, dummyalbum, composer, duplicate, albumtype, tracknumber)''')
#            c.execute('''create index inxTrackNumbersGenreArtistAlbumType on TrackNumbers (genre, artist, album, albumtype)''')
#            c.execute('''create index inxTrackNumbersGenreArtistAlbumDup on TrackNumbers (genre, artist, album, duplicate)''')
#            c.execute('''create index inxTrackNumbersGenreArtistAlbumNum on TrackNumbers (genre, artist, album, albumtype, tracknumber)''')
#            c.execute('''create index inxTrackNumbersArtistAlbumType on TrackNumbers (artist, album, albumtype)''')
#            c.execute('''create index inxTrackNumbersArtistAlbumDup on TrackNumbers (artist, album, duplicate)''')
#            c.execute('''create index inxTrackNumbersArtistAlbumNum on TrackNumbers (artist, album, albumtype, tracknumber)''')
#            c.execute('''create index inxTrackNumbersComposerAlbumType on TrackNumbers (composer, album, albumtype)''')
#            c.execute('''create index inxTrackNumbersComposerAlbumDup on TrackNumbers (composer, album, duplicate)''')
#            c.execute('''create index inxTrackNumbersComposerAlbumNum on TrackNumbers (composer, album, albumtype, tracknumber)''')

    except sqlite3.Error, e:
        errorstring = "Error creating database: %s, %s" % (database, e)
        filelog.write_error(errorstring)
    db.commit()
    c.close()

def empty_database(database):
    db = sqlite3.connect(database)
    c = db.cursor()
    try:
        c.execute('''drop table if exists params''')
#        c.execute('''drop table if exists sorts''')
        c.execute('''drop table if exists tracks''')
        c.execute('''drop table if exists albums''')
        c.execute('''drop table if exists artists''')
        c.execute('''drop table if exists composers''')
        c.execute('''drop table if exists genres''')
#        c.execute('''drop table if exists playlists''')
        c.execute('''drop table if exists GenreArtist''')
        c.execute('''drop table if exists GenreAlbumartist''')
        c.execute('''drop table if exists GenreArtistAlbum''')
        c.execute('''drop table if exists GenreAlbumartistAlbum''')
        c.execute('''drop table if exists ArtistAlbum''')
        c.execute('''drop table if exists AlbumartistAlbum''')
        c.execute('''drop table if exists ComposerAlbum''')
        c.execute('''drop table if exists GenreArtistAlbumTrack''')
        c.execute('''drop table if exists GenreAlbumartistAlbumTrack''')
        c.execute('''drop table if exists ArtistAlbumTrack''')
        c.execute('''drop table if exists AlbumartistAlbumTrack''')
        c.execute('''drop table if exists ComposerAlbumTrack''')
        c.execute('''drop table if exists TrackNumbers''')
    except sqlite3.Error, e:
        errorstring = "Error dropping table: %s, %s" % (table, e)
        filelog.write_error(errorstring)
    db.commit()
    c.close()

def process_command_line(argv):
    """
        Return a 2-tuple: (settings object, args list).
        `argv` is a list of arguments, or `None` for ``sys.argv[1:]``.
    """
    if argv is None:
        argv = sys.argv[1:]

    # initialize parser object
    parser = optparse.OptionParser(
        formatter=optparse.TitledHelpFormatter(width=78),
        add_help_option=None)

    # options
    parser.add_option("-s", "--tagdatabase", dest="tagdatabase", type="string", 
                      help="read tags from source DATABASE", action="store",
                      metavar="TAGDATABASE")
    parser.add_option("-d", "--trackdatabase", dest="trackdatabase", type="string", 
                      help="write tags to destination DATABASE", action="store",
                      metavar="TRACKDATABASE")
    parser.add_option("-t", "--the", dest="the_processing", type="string", 
                      help="how to process 'the' before artist name (before/after(default)/remove)", 
                      action="store", default='remove',
                      metavar="THE")
    parser.add_option("-c", "--count", dest="scancount", type="int", 
                      help="process 'count' number of scans", action="store",
                      metavar="COUNT")
    parser.add_option("-r", "--regenerate",
                      action="store_true", dest="regenerate", default=False,
                      help="regenerate database")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="print verbose status messages to stdout")
    parser.add_option("-q", "--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="don't print status messages to stdout")
    parser.add_option('-h', '--help', action='help',
                      help='Show this help message and exit.')
    settings, args = parser.parse_args(argv)
    return settings, args

def main(argv=None):
    options, args = process_command_line(argv)
    filelog.set_log_type(options.quiet, options.verbose)
    filelog.open_log_files()
    if len(args) != 0 or not options.tagdatabase or not options.trackdatabase: 
        print "Usage: %s [options]" % sys.argv[0]
    else:
        tagdatabase = options.tagdatabase
        trackdatabase = options.trackdatabase
        if not os.path.isabs(tagdatabase):
            tagdatabase = os.path.join(os.getcwd(), tagdatabase)
        if not os.path.isabs(trackdatabase):
            trackdatabase = os.path.join(os.getcwd(), trackdatabase)
        if options.regenerate:
            empty_database(trackdatabase)
        check_target_database_exists(trackdatabase)
        process_tags(args, options, tagdatabase, trackdatabase)
    filelog.close_log_files()
    return 0

if __name__ == "__main__":
    status = main()
    sys.exit(status)

