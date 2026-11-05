"""Vision Module - Face Detection, Object Recognition, Scene Understanding"""
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple, Callable
from dataclasses import dataclass
from pathlib import Path
import pickle
import threading
import time
from PIL import Image

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False

from config.settings import vision_config, DATA_DIR
from utils.logger import get_logger

logger = get_logger("vision_module")

@dataclass
class FaceDetection:
    """Detected face information"""
    location: Tuple[int, int, int, int]  # top, right, bottom, left
    encoding: Optional[np.ndarray] = None
    name: Optional[str] = None
    confidence: float = 0.0

@dataclass
class ObjectDetection:
    """Detected object information"""
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h

@dataclass
class SceneInfo:
    """Scene understanding results"""
    description: str
    objects: List[ObjectDetection]
    faces: List[FaceDetection]
    brightness: float
    motion_detected: bool

class FaceRecognition:
    """Face recognition using face_recognition library"""
    
    def __init__(self):
        self.known_faces: Dict[str, np.ndarray] = {}
        self.known_faces_path = Path(vision_config.known_faces_path) / "known_faces.pkl"
        self.tolerance = vision_config.recognition_tolerance
        self._load_known_faces()
    
    def _load_known_faces(self):
        """Load known face encodings"""
        if self.known_faces_path.exists():
            try:
                with open(self.known_faces_path, 'rb') as f:
                    self.known_faces = pickle.load(f)
                logger.info(f"Loaded {len(self.known_faces)} known faces")
            except Exception as e:
                logger.error(f"Failed to load known faces: {e}")
    
    def _save_known_faces(self):
        """Save known face encodings"""
        try:
            self.known_faces_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.known_faces_path, 'wb') as f:
                pickle.dump(self.known_faces, f)
        except Exception as e:
            logger.error(f"Failed to save known faces: {e}")
    
    def register_face(self, name: str, image: np.ndarray) -> bool:
        """Register a new face"""
        if not FACE_RECOGNITION_AVAILABLE:
            logger.warning("face_recognition not available")
            return False
        
        try:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            encodings = face_recognition.face_encodings(rgb_image)
            
            if encodings:
                self.known_faces[name] = encodings[0]
                self._save_known_faces()
                logger.info(f"Registered face for {name}")
                return True
            else:
                logger.warning("No face found in image")
                return False
                
        except Exception as e:
            logger.error(f"Face registration failed: {e}")
            return False
    
    def recognize_faces(self, image: np.ndarray) -> List[FaceDetection]:
        """Detect and recognize faces in image"""
        if not FACE_RECOGNITION_AVAILABLE:
            return []
        
        try:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_image, model=vision_config.face_detection_model)
            face_encodings = face_recognition.face_encodings(rgb_image, face_locations)
            
            detections = []
            for location, encoding in zip(face_locations, face_encodings):
                name = "Unknown"
                confidence = 0.0
                
                # Compare with known faces
                if self.known_faces:
                    matches = face_recognition.compare_faces(
                        list(self.known_faces.values()), 
                        encoding, 
                        tolerance=self.tolerance
                    )
                    face_distances = face_recognition.face_distance(
                        list(self.known_faces.values()), 
                        encoding
                    )
                    
                    if True in matches:
                        best_match_index = np.argmin(face_distances)
                        name = list(self.known_faces.keys())[best_match_index]
                        confidence = 1 - face_distances[best_match_index]
                
                detections.append(FaceDetection(
                    location=location,
                    encoding=encoding,
                    name=name,
                    confidence=confidence
                ))
            
            return detections
            
        except Exception as e:
            logger.error(f"Face recognition error: {e}")
            return []

class ObjectDetector:
    """Object detection using OpenCV DNN or YOLO"""
    
    def __init__(self):
        self.net = None
        self.classes = []
        self.colors = []
        self._load_model()
    
    def _load_model(self):
        """Load YOLO or MobileNet model"""
        try:
            # Try to load MobileNet SSD (lighter, faster)
            model_path = DATA_DIR / "models"
            model_path.mkdir(parents=True, exist_ok=True)
            
            # Use OpenCV's DNN face detector as fallback
            self.face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            
            # COCO class names for YOLO (if available)
            self.classes = [
                "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
                "truck", "boat", "traffic light", "fire hydrant", "stop sign",
                "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
                "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
                "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
                "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
                "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
                "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
                "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
                "couch", "potted plant", "bed", "dining table", "toilet", "tv",
                "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
                "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
                "scissors", "teddy bear", "hair drier", "toothbrush"
            ]
            
        except Exception as e:
            logger.warning(f"Could not load detection model: {e}")
    
    def detect_objects(self, image: np.ndarray) -> List[ObjectDetection]:
        """Detect objects in image"""
        detections = []
        
        # Simple object detection using color and contour analysis
        # This is a basic fallback - real implementation would use YOLO/SSD
        
        try:
            # Detect people using HOG
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            boxes, weights = hog.detectMultiScale(gray, winStride=(8,8))
            
            for (x, y, w, h), weight in zip(boxes, weights):
                if weight > 0.5:
                    detections.append(ObjectDetection(
                        label="person",
                        confidence=float(weight),
                        bbox=(x, y, w, h)
                    ))
            
            # Detect faces
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            for (x, y, w, h) in faces:
                detections.append(ObjectDetection(
                    label="face",
                    confidence=0.8,
                    bbox=(x, y, w, h)
                ))
                
        except Exception as e:
            logger.error(f"Object detection error: {e}")
        
        return detections

class SceneAnalyzer:
    """Analyze scene for context understanding"""
    
    def analyze(self, image: np.ndarray, objects: List[ObjectDetection], 
                faces: List[FaceDetection]) -> str:
        """Generate scene description"""
        parts = []
        
        # Count objects
        obj_counts = {}
        for obj in objects:
            obj_counts[obj.label] = obj_counts.get(obj.label, 0) + 1
        
        # Count faces
        known_faces = [f for f in faces if f.name != "Unknown"]
        unknown_faces = [f for f in faces if f.name == "Unknown"]
        
        # Build description
        if known_faces:
            names = ", ".join([f.name for f in known_faces])
            parts.append(f"I see {names}")
        
        if unknown_faces:
            count = len(unknown_faces)
            if count == 1:
                parts.append("there's one other person")
            else:
                parts.append(f"there are {count} other people")
        
        # Describe main objects
        main_objects = [label for label, count in obj_counts.items() 
                       if label not in ['face', 'person'] and count > 0]
        
        if main_objects:
            if len(main_objects) <= 3:
                parts.append(f"I also see {', '.join(main_objects)}")
            else:
                parts.append(f"The scene contains {len(main_objects)} different objects")
        
        # Analyze brightness
        brightness = np.mean(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        if brightness < 50:
            parts.append("it's quite dark")
        elif brightness > 200:
            parts.append("it's very bright")
        
        if parts:
            return "In this scene, " + ", ".join(parts) + "."
        return "I see an empty scene."

class VisionModule:
    """Main vision orchestrator"""
    
    def __init__(self):
        self.camera_index = vision_config.camera_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.face_recognition = FaceRecognition()
        self.object_detector = ObjectDetector()
        self.scene_analyzer = SceneAnalyzer()
        self._running = False
        self._detection_thread: Optional[threading.Thread] = None
        self._last_frame: Optional[np.ndarray] = None
        self._last_scene_info: Optional[SceneInfo] = None
        self._on_detection: Optional[Callable] = None
    
    def start_camera(self) -> bool:
        """Initialize camera capture"""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                logger.error("Failed to open camera")
                return False
            
            # Set resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            logger.info("Camera started")
            return True
            
        except Exception as e:
            logger.error(f"Camera error: {e}")
            return False
    
    def stop_camera(self):
        """Stop camera capture"""
        self._running = False
        if self._detection_thread:
            self._detection_thread.join(timeout=1)
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        cv2.destroyAllWindows()
        logger.info("Camera stopped")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture single frame"""
        if not self.cap:
            return None
        
        ret, frame = self.cap.read()
        if ret:
            return frame
        return None
    
    def analyze_frame(self, frame: np.ndarray) -> SceneInfo:
        """Analyze a single frame"""
        # Detect objects
        objects = self.object_detector.detect_objects(frame)
        
        # Detect and recognize faces
        faces = self.face_recognition.recognize_faces(frame)
        
        # Analyze brightness
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)
        
        # Detect motion (simple frame differencing)
        motion_detected = False
        if self._last_frame is not None:
            diff = cv2.absdiff(gray, cv2.cvtColor(self._last_frame, cv2.COLOR_BGR2GRAY))
            motion_score = np.mean(diff)
            motion_detected = motion_score > 10
        
        self._last_frame = frame.copy()
        
        # Generate description
        description = self.scene_analyzer.analyze(frame, objects, faces)
        
        return SceneInfo(
            description=description,
            objects=objects,
            faces=faces,
            brightness=brightness,
            motion_detected=motion_detected
        )
    
    def start_continuous_detection(self, callback: Optional[Callable] = None):
        """Start continuous detection in background"""
        self._on_detection = callback
        self._running = True
        self._detection_thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._detection_thread.start()
    
    def _detection_loop(self):
        """Main detection loop"""
        while self._running:
            frame = self.capture_frame()
            if frame is not None:
                scene_info = self.analyze_frame(frame)
                self._last_scene_info = scene_info
                
                if self._on_detection:
                    self._on_detection(scene_info)
            
            time.sleep(0.1)  # 10 FPS
    
    def get_last_scene_info(self) -> Optional[SceneInfo]:
        """Get last analyzed scene info"""
        return self._last_scene_info
    
    def register_new_face(self, name: str) -> bool:
        """Register face from current frame"""
        frame = self.capture_frame()
        if frame is not None:
            return self.face_recognition.register_face(name, frame)
        return False
    
    def get_frame_with_annotations(self) -> Optional[np.ndarray]:
        """Get current frame with detection annotations"""
        frame = self._last_frame
        if frame is None:
            return None
        
        annotated = frame.copy()
        
        if self._last_scene_info:
            # Draw faces
            for face in self._last_scene_info.faces:
                top, right, bottom, left = face.location
                color = (0, 255, 0) if face.name != "Unknown" else (0, 0, 255)
                cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
                
                label = f"{face.name} ({face.confidence:.2f})"
                cv2.putText(annotated, label, (left, top - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Draw objects
            for obj in self._last_scene_info.objects:
                x, y, w, h = obj.bbox
                cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(annotated, f"{obj.label} ({obj.confidence:.2f})",
                           (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
        
        return annotated
    
    def save_snapshot(self, path: str) -> bool:
        """Save current frame to file"""
        frame = self._last_frame
        if frame is not None:
            cv2.imwrite(path, frame)
            return True
        return False
