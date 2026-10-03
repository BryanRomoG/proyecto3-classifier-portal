from fastapi import FastAPI, File, UploadFile, HTTPException 
from inference 
import predict 
app = FastAPI( title="Image Classifier Inference", )
@app.get("/health") def health(): return { "status": "ok", }

@app.post("/predict")
async def predict_endpoint(
  file: UploadFile = File(...), ):

    if not file.content_type: 
      raise HTTPException( 
        status_code=400,
        detail="La imagen no tiene content-type.", )
      
      allowed_types = { "image/jpeg", "image/png", "image/webp", }
      if file.content_type not in allowed_types: 
        raise HTTPException( status_code=400, detail="Formato de imagen no soportado.", ) 
        
      data = await file.read() 
        
      if len(data) > 10 * 1024 * 1024:
         raise HTTPException( status_code=413, detail="La imagen supera los 10 MB.", )
          
      try: result = predict( data, file.content_type, )
        return result 
except Exception as exc: 
raise HTTPException( status_code=500, detail=str(exc), ) from exc

