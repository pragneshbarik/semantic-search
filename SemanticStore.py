import os
import uuid
import requests
import sqlite3
from utils import * 
from StoreObjects import *
from collections import defaultdict
from pipelines.TextPipeline import TextPipeline
from pipelines.ImagePipeline import ImagePipeline
from pipelines.AudioPipeline import AudioPipeline





class Store:
    def __init__(self) :
        self.__is_connected = False
        

    
    def connect(self, store_uri: str) :
        sql_uri = store_uri.split('.')[0]  + ".db"
        self.__db_connection = sqlite3.connect(sql_uri)
        self.__db = self.__db_connection.cursor()


        text_index = sql_uri + '_text.faiss'
        image_index = sql_uri + '_image.faiss'

        self.__image_pipeline = ImagePipeline(faiss_uri=image_index, sqlite_uri=sql_uri)
        self.__text_pipeline = TextPipeline(faiss_uri=text_index, sqlite_uri=sql_uri)
        self.__audio_pipeline = AudioPipeline(faiss_uri=text_index, sqlite_uri=sql_uri)

        self.__pipelines = {
            "image" : self.__image_pipeline,
            "text" : self.__text_pipeline,
            "audio" : self.__audio_pipeline
        }

        self.__is_connected = True

        self.__db.execute(
        '''
        CREATE TABLE IF NOT EXISTS master_file_record (
            uuid TEXT PRIMARY KEY,
            file_path TEXT,
            file_type TEXT,
            faiss_start_index TEXT,
            faiss_end_index TEXT
        )
        '''
        )

        self.__db.execute(
            '''
            CREATE TABLE IF NOT EXISTS deleted_ids (
                table_type TEXT,
                faiss_index INTEGER
            )
            '''

        )

        self.commit()


    def multimodal_search(self, path: str, k: int, left: str, right: str) :
        pass

    # def _text_to_text_search(self, q:str, k: int) :
    #     self.pipelines['text'].similarity_search(q, k)
    

    def _text_to_image_search(self, q:str, k: int) :

        if(len(split_text(q))<50) :
            images, distances = self.__image_pipeline.similarity_search(q, k)

            image_objects = []
            for image, dist in zip(images, distances):
                image_object = ImageObject(image[1], image[2], dist)
                image_objects.append(image_object)

        return image_objects
    
    def _text_to_text_search(self, q: str, k:int) :
        temp_texts, distances = self.__text_pipeline.similarity_search(q, k)
                
        texts = []
        for text, d in zip(temp_texts, list(distances)) :
            texts.append(list(text) + [d])
        
        texts_dict = defaultdict(list)
        for text in texts :
            texts_dict[text[1]].append(text)

        text_objects = []

        for uuid in texts_dict :
            text_object = TextObject(uuid, texts_dict[uuid][0][2], [], [])
            for text in texts_dict[uuid] :
                text_object.chunks.append(text[3])
                text_object.distances.append(text[4])
            
            text_objects.append(text_object)
        
        return text_objects
            

    def _text_to_audio_search(self, q: str, k: int) :
        temp_audios, distances = self.__audio_pipeline.similarity_search(q, k)
                
        audios = []
        for audio, d in zip(temp_audios, list(distances)) :
            audios.append(list(audio) + [d])
        
        audio_dict = defaultdict(list)

        for audio in audios :
            audio_dict[audio[1]].append(audio)


        audio_objects = []

        for uuid in audio_dict :
            audio_object = AudioObject(uuid, audio_dict[uuid][0][2], [], [])
            for audio in audio_dict[uuid] :
                audio_object.chunks.append(audio[3])
                audio_object.distances.append(audio[4])
            
            audio_objects.append(audio_object)
        
        return audio_objects

    def _image_to_image_search(self, path: str, k:int) :
        images, distances = self.__image_pipeline.image_to_image_search(path, k)

        image_objects = []
        for image, dist in zip(images, distances):
            image_object = ImageObject(image[1], image[2], dist)
            image_objects.append(image_object)
        
        return image_objects

    def _audio_to_text_search(self, path: str, k:int) :
        pass



    def _audio_to_image_search(self, path: str, k: int):
        pass

    def _audio_to_audio_search(self, path: str, k: int) :
        pass

    
    def search(self, q: str, k: int, modals=['text']) :

        s = StoreObject()

        if 'image' in modals :
            image_objects = self._text_to_image_search(q, k)
            s.images = image_objects
        
        if 'text' in modals :
            text_objects = self._text_to_text_search(q, k)
            s.texts = text_objects

        if 'audio' in modals :
            audio_objects = self._text_to_audio_search(q, k)
            s.audios = audio_objects
            
        
        return s;
        

    def __determine_modality(self, path: str):
        file_extension = path.split(".")[-1].lower()
        if file_extension in ["jpg", "jpeg", "png"]:
            return "image"
        elif file_extension in ["txt", "pdf"]:
            return "text"
        elif file_extension in ["mp3", "wav", "flac"]:
            return "audio"
        else:
            return "unsupported"  # Modify as needed for your specific use case

    def __sql_insert_into_master_file_record(self, file_id, file_path, modality, faiss_start_index, faiss_end_index):
        query = "INSERT INTO master_file_record (uuid, file_path, file_type, faiss_start_index, faiss_end_index) VALUES (?, ?, ?, ?, ?)"
        values = (file_id, file_path, modality, faiss_start_index, faiss_end_index)
    
        self.__db.execute(query, values)
        self.commit()


    def __insert_local(self, path: str) :
        if not self.__is_connected:
            print("Not connected to the database. Call connect() first.")
            return

       
        modality = self.__determine_modality(path)


        if modality not in self.__pipelines:
            print("Unsupported modality.")
            return

        file_id = str(uuid.uuid4())
        pipeline = self.__pipelines[modality]
        file_id, first_index, last_index = pipeline.insert_file(path, file_id)
        

        self.__sql_insert_into_master_file_record(file_id, path, modality, first_index, last_index)
        return file_id;

   
    def __insert_remote(self, uri: str):
        try:
            response = requests.get(uri)
            if response.status_code == 200:
                file_id = str(uuid.uuid4())
                content_type = response.headers.get('content-type')
                
                if content_type:
                    file_extension = content_type.split('/')[-1]
                else:
                    file_extension = os.path.splitext(uri)[1].strip('.')
                
                temp_filename = file_id + '.' + file_extension
                
                with open(temp_filename, 'wb') as temp_file:
                    temp_file.write(response.content)
                
                modality = self.__determine_modality(temp_filename)
                
                if modality not in self.__pipelines:
                    print("Unsupported modality.")
                    return

                pipeline = self.__pipelines[modality]
                file_id, first_index, last_index = pipeline.insert_file(temp_filename, file_id)

                self.__sql_insert_into_master_file_record(file_id, uri, modality, first_index, last_index)
                os.remove(temp_filename)
                return file_id
                
            else:
                print("Failed to fetch remote file. Status code:", response.status_code)
                return None
        except Exception as e:
            print("Error inserting remote file:", str(e))
            return None


    def insert(self, path: str):
        if path.startswith(('http://', 'https://', 'ftp://')):  
            return self.__insert_remote(path)
        else:
            return self.__insert_local(path)



    
    def get(self, uuid: str) :
        q = f"SELECT * FROM master_file_record WHERE uuid = '{uuid}'"
        res = self.__db.execute(q).fetchone()
        f = FileObject(res[0], res[1], res[2])
        return f;

    def delete(self, uuid: str) :
        pass    



    def commit(self) :
        self.__image_pipeline.commit()
        self.__audio_pipeline.commit()
        self.__text_pipeline.commit()
        self.__db_connection.commit()

    def _db(self) :
        return self.__db




# import Store from SemanticStore

store = Store()
store.connect('some2.db')
# store.insert('https://images.pexels.com/photos/3617500/pexels-photo-3617500.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1')
# store.commit()

res = store.search(q="some class", k=1, modals=['image'])
# res = store.search("what is meaning of life according to gita ?", 5, modals=['text', 'image'])

print(res)

# image_pipeline = ImagePipeline(faiss_uri='image.faiss', sqlite_uri='image.db')
# image_pipeline.insert_file('cat.jpg')

# image_pipeline.commit()
# res = image_pipeline.similarity_search(q="a dog", k=1);
# print(res);

