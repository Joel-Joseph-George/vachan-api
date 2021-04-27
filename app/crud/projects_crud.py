''' Place to define all data processing and Database CRUD operations for
AgMT Project Management. The translation or NLP related functions of these
projects are included in nlp_crud module'''

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

#pylint: disable=E0401, disable=E0611
#pylint gives import error if not relative import is used. But app(uvicorn) doesn't accept it

import db_models
from crud import utils, nlp_crud
from custom_exceptions import NotAvailableException, TypeException

#pylint: disable=too-many-branches, disable=too-many-locals, disable=too-many-arguments
#pylint: disable=too-many-statements, disable=W0102, disable=too-many-nested-blocks

###################### AgMT Project Mangement ######################
def create_agmt_project(db_:Session, project, user_id=None):
    '''Add a new project entry to the translation projects table'''
    source = db_.query(db_models.Language).filter(
        db_models.Language.code==project.sourceLanguageCode).first()
    target = db_.query(db_models.Language).filter(
        db_models.Language.code==project.targetLanguageCode).first()
    meta= {}
    meta["books"] = []
    meta["useDataForLearning"] = project.useDataForLearning
    if project.stopwords:
        meta['stopwords'] = project.stopwords.__dict__
    if project.punctuations:
        meta['punctuations'] = project.punctuations
    db_content = db_models.TranslationProject(
        projectName=utils.normalize_unicode(project.projectName),
        source_lang_id=source.languageId,
        target_lang_id=target.languageId,
        documentFormat=project.documentFormat.value,
        active=project.active,
        createdUser=user_id,
        updatedUser=user_id,
        metaData=meta
        )
    db_.add(db_content)
    db_.flush()
    db_content2 = db_models.TranslationProjectUser(
        project_id=db_content.projectId,
        userId=user_id,
        userRole="owner",
        active=True)
    db_.add(db_content2)
    db_.commit()
    return db_content

def update_agmt_project(db_:Session, project_obj, user_id=None):
    '''Either activate or deactivate a project or Add more books to a project,
    adding all new verses to the drafts table'''
    project_row = db_.query(db_models.TranslationProject).get(project_obj.projectId)
    if not project_row:
        raise NotAvailableException("Project with id, %s, not found"%project_obj.projectId)
    new_books = []
    if project_obj.selectedBooks:
        if not project_obj.selectedBooks.bible.endswith("_"+db_models.ContentTypeName.bible.value):
            raise TypeException("Operation only supported on Bible tables")
        if not project_obj.selectedBooks.bible+"_cleaned" in db_models.dynamicTables:
            raise NotAvailableException("Bible, %s, not found"%project_obj.selectedBooks.bible)
        bible_cls = db_models.dynamicTables[project_obj.selectedBooks.bible+"_cleaned"]
        verse_query = db_.query(bible_cls)
        for buk in project_obj.selectedBooks.books:
            book = db_.query(db_models.BibleBook).filter(
                db_models.BibleBook.bookCode == buk).first()
            if not book:
                raise NotAvailableException("Book, %s, not found in database" %buk)
            new_books.append(buk)
            refid_start = book.bookId * 1000000
            refid_end = refid_start + 999999
            verses = verse_query.filter(
                bible_cls.refId >= refid_start, bible_cls.refId <= refid_end).all()
            if len(verses) == 0:
                raise NotAvailableException("Book, %s, is empty for %s"%(
                    buk, project_obj.selectedBooks.bible))
            for verse in verses:
                sent = utils.normalize_unicode(verse.verseText)
                offsets = [0, len(sent)]
                draft_row = db_models.TranslationDraft(
                    project_id=project_obj.projectId,
                    sentenceId=verse.refId,
                    surrogateId=buk+","+str(verse.chapter)+","+str(verse.verseNumber),
                    sentence=sent,
                    draft=sent,
                    draftMeta=[[offsets,offsets,"untranslated"]],
                    updatedUser=user_id)
                db_.add(draft_row)
    if project_obj.uploadedBooks:
        for usfm in project_obj.uploadedBooks:
            usfm_json = utils.parse_usfm(usfm)
            book_code = usfm_json['book']['bookCode'].lower()
            book = db_.query(db_models.BibleBook).filter(
                db_models.BibleBook.bookCode == book_code).first()
            if not book:
                raise NotAvailableException("Book, %s, not found in database"% book_code)
            new_books.append(book_code)
            for chap in usfm_json['chapters']:
                chapter_number = chap['chapterNumber']
                for cont in chap['contents']:
                    if "verseNumber" in cont:
                        verse_number = cont['verseNumber']
                        verse_text = cont['verseText']
                        offsets = [0, len(verse_text)]
                        draft_row = db_models.TranslationDraft(
                            project_id=project_obj.projectId,
                            sentenceId=book.bookId*1000000+
                                int(chapter_number)*1000+int(verse_number),
                            surrogateId=book_code+","+str(chapter_number)+","+str(verse_number),
                            sentence=verse_text,
                            draft=verse_text,
                            draftMeta=[[offsets,offsets,'untranslated']],
                            updatedUser=user_id)
                        db_.add(draft_row)
    db_.commit()
    db_.expire_all()
    if project_obj.active is not None:
        project_row.active = project_obj.active
    if project_obj.useDataForLearning is not None:
        project_row.metaData['useDataForLearning'] = project_obj.useDataForLearning
        flag_modified(project_row, "metaData")
    if project_obj.stopwords:
        project_row.metaData['stopwords'] = project_obj.stopwords.__dict__
    if project_obj.punctuations:
        project_row.metaData['punctuations'] = project_obj.punctuations
    project_row.updatedUser = user_id
    if len(new_books) > 0:
        project_row.metaData['books'] += new_books
        flag_modified(project_row, "metaData")
    db_.add(project_row)
    db_.commit()
    db_.refresh(project_row)
    return project_row

def get_agmt_projects(db_:Session, project_name=None, source_language=None, target_language=None,
    active=True, user_id=None, skip=0, limit=100):
    '''Fetch autographa projects as per the query options'''
    query = db_.query(db_models.TranslationProject)
    if project_name:
        query = query.filter(
            db_models.TranslationProject.projectName == utils.normalize_unicode(project_name))
    if source_language:
        source = db_.query(db_models.Language).filter(db_models.Language.code == source_language
            ).first()
        if not source:
            raise NotAvailableException("Language, %s, not found"%source_language)
        query = query.filter(db_models.TranslationProject.source_lang_id == source.languageId)
    if target_language:
        target = db_.query(db_models.Language).filter(db_models.Language.code == target_language
            ).first()
        if not target:
            raise NotAvailableException("Language, %s, not found"%target_language)
        query = query.filter(db_models.TranslationProject.target_lang_id == target.languageId)
    if user_id:
        query = query.filter(db_models.TranslationProject.users.any(userId=user_id))
    query = query.filter(db_models.TranslationProject.active == active)
    return query.offset(skip).limit(limit).all()

def add_agmt_user(db_:Session, project_id, user_id, current_user=None):
    '''Add an additional user(not the created user) to a project, in translation_project_users'''
    project_row = db_.query(db_models.TranslationProject).get(project_id)
    if not project_row:
        raise NotAvailableException("Project with id, %s, not found"%project_id)
    db_content = db_models.TranslationProjectUser(
        project_id=project_id,
        userId=user_id,
        userRole='member',
        active=True)
    db_.add(db_content)
    project_row.updatedUser = current_user
    db_.commit()
    return db_content

def update_agmt_user(db_, user_obj, current_user=10101):
    '''Change role, active status or metadata of user in a project'''
    user_row = db_.query(db_models.TranslationProjectUser).filter(
        db_models.TranslationProjectUser.project_id == user_obj.project_id,
        db_models.TranslationProjectUser.userId == user_obj.userId).first()
    if not user_row:
        raise NotAvailableException("User-project pair not found")
    if user_obj.userRole:
        user_row. userRole = user_obj.userRole
    if user_obj.metaData:
        user_row.metaData = user_obj.metaData
        flag_modified(user_row,'metaData')
    if user_obj.active is not None:
        user_row.active = user_obj.active
    user_row.project.updatedUser = current_user
    db_.add(user_row)
    db_.commit()
    return user_row


def obtain_agmt_draft(db_:Session, project_id, books, sentence_id_list, sentence_id_range,
    output_format="usfm"):
    '''generate draft for selected sentences as usfm or json'''
    project_row = db_.query(db_models.TranslationProject).get(project_id)
    if not project_row:
        raise NotAvailableException("Project with id, %s, not found"%project_id)
    draft_rows = nlp_crud.obtain_agmt_source(db_, project_id, books, sentence_id_list,
    	sentence_id_range, with_draft=True)
    if output_format.value == "usfm":
        return nlp_crud.create_usfm(draft_rows)
    if output_format.value == 'alignment-json':
        return nlp_crud.export_to_json(project_row.sourceLanguage,
            project_row.targetLanguage, draft_rows, None)
    raise TypeException("Unsupported output format: %s"%output_format)

def obtain_agmt_progress(db_, project_id, books, sentence_id_list, sentence_id_range):
    '''Calculate project translation progress in terms of how much of draft is translated'''
    project_row = db_.query(db_models.TranslationProject).get(project_id)
    if not project_row:
        raise NotAvailableException("Project with id, %s, not found"%project_id)
    draft_rows = nlp_crud.obtain_agmt_source(db_, project_id, books, sentence_id_list,
    	sentence_id_range, with_draft=True)
    confirmed_length = 0
    suggestions_length = 0
    untranslated_length = 0
    for row in draft_rows:
        for segment in row.draftMeta:
            token_len = segment[0][1] - segment[0][0]
            if token_len <= 1:
                continue #possibly spaces or punctuations
            if segment[2] == "confirmed":
                confirmed_length += token_len
            elif segment[2] == "suggestion":
                suggestions_length += token_len
            else:
                untranslated_length += token_len
    total_length = confirmed_length + suggestions_length + untranslated_length
    result = {"confirmed": confirmed_length/total_length,
        "suggestion": suggestions_length/total_length,
        "untranslated": untranslated_length/total_length}
    return result
