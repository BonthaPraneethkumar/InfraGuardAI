INFRAGUARD AI — START HERE
==========================

You do NOT need to understand Python to run this hackathon MVP.

FIRST RUN
1. Extract the ZIP to a normal folder.
2. Double-click START_INFRAGUARD.bat
3. The first run may take several minutes because it installs required packages.
4. Chrome/your default browser should open:
   http://127.0.0.1:8000
5. Keep the black command window open while using the app.

REAL SARVAM AI
1. Open the file named .env using VS Code or Notepad.
2. Find:
   SARVAM_API_KEY=
3. Paste your key after the = sign. Do not add quotes.
4. Save the file.
5. Close the server window and double-click START_INFRAGUARD.bat again.
6. At the top of the app you should see: "Sarvam AI connected".

WITHOUT A SARVAM KEY
The app still works in Demo AI mode using local rule-based classification.
Voice-to-text requires the Sarvam key, but you can type the complaint manually.

DEMO TO SHOW JUDGES
1. Report an Issue
2. Take/upload a road pothole photo with no people in it.
3. Record: "There is a large pothole in the middle of the road. Vehicles are swerving and it may cause an accident."
4. Convert Voice to Text.
5. Use Current Location and type a location label.
6. Analyze Complaint.
7. Submit.
8. Open Officer.
9. Change Registered -> Assigned -> In Progress.
10. Add a note and upload a resolution photo.
11. Change status to Resolved.
12. Open My Reports and show the citizen's update.
13. Open Analytics.

IMPORTANT PRIVACY LIMITATION
The current MVP privacy gate automatically looks for faces, human figures and QR codes.
It is NOT a production-grade detector for every possible ID card, license plate, phone number
or other sensitive text. Citizen images are NEVER sent to Sarvam AI in this MVP.
