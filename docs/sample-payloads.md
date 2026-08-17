# Attachment C: Sample Request/Response Payloads

---

## 1. Intelligence Database API

### Configuration
```
Endpoint  : GET https://akirs-tms.net/intelligence_db/api/v1/intelligence/intelligenceGathering
Auth      : Bearer {token}
Query Params: page, limit, search
```

### Request
```
GET /intelligence_db/api/v1/intelligence/intelligenceGathering?page=1&limit=10&search=John+Doe HTTP/1.1
Host: akirs-tms.net
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Accept: application/json
Origin: https://ibomtax.net
Referer: https://ibomtax.net/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...
```

### Response (200 OK)
```json
{
  "data": [
    {
      "taxPayerName": "John Doe Enterprises",
      "email": "john@example.com",
      "phone": "08031234567",
      "natureOfBusiness": "General Merchandise",
      "address": "123 Abak Road, Uyo, Akwa Ibom State"
    },
    {
      "taxPayerName": "Jane Doe Ventures",
      "email": "jane@example.com",
      "phone": "08039876543",
      "natureOfBusiness": "Transportation",
      "address": "45 Oron Road, Uyo"
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 10
}
```

### Response (401 Unauthorized)
```json
{
  "statusCode": 401,
  "message": "Unauthorized",
  "error": "Invalid or expired token"
}
```

---

## 2. Paystack NUBAN Resolution API

### Request — Bank List
```
GET https://api.paystack.co/bank HTTP/1.1
Authorization: Bearer sk_live_xxxxxxxxxxxxxxxxxxxx
```

### Response (200 OK)
```json
{
  "status": true,
  "message": "Banks retrieved",
  "data": [
    { "name": "Access Bank",   "code": "044", "longcode": "044150149", "gateway": null, "active": true, "id": 1, "is_deleted": null, "country": "Nigeria", "currency": "NGN", "type": "nuban" },
    { "name": "First Bank",    "code": "011", "longcode": "011151003", "gateway": null, "active": true, "id": 2, "is_deleted": null, "country": "Nigeria", "currency": "NGN", "type": "nuban" },
    { "name": "GTBank",        "code": "058", "longcode": "058152036", "gateway": null, "active": true, "id": 3, "is_deleted": null, "country": "Nigeria", "currency": "NGN", "type": "nuban" },
    { "name": "UBA",           "code": "033", "longcode": "033153013", "gateway": null, "active": true, "id": 4, "is_deleted": null, "country": "Nigeria", "currency": "NGN", "type": "nuban" },
    { "name": "Sterling Bank", "code": "232", "longcode": "232150016", "gateway": null, "active": true, "id": 5, "is_deleted": null, "country": "Nigeria", "currency": "NGN", "type": "nuban" }
  ]
}
```

### Request — Account Resolution
```
GET https://api.paystack.co/bank/resolve?account_number=0123456789&bank_code=044 HTTP/1.1
Authorization: Bearer sk_live_xxxxxxxxxxxxxxxxxxxx
```

### Response — Success
```json
{
  "status": true,
  "message": "Account number resolved",
  "data": {
    "account_number": "0123456789",
    "account_name": "JOHN DOE",
    "bank_id": 1
  }
}
```

### Response — Not Found
```json
{
  "status": false,
  "message": "Could not resolve account number",
  "data": null
}
```

---

## 3. Flutterwave NUBAN Resolution API (Fallback)

### Request
```
POST https://api.flutterwave.com/v3/accounts/resolve HTTP/1.1
Host: api.flutterwave.com
Authorization: Bearer FLWSECK-xxxxxxxxxxxxxxxxxxxx
Content-Type: application/json

{
  "account_number": "0123456789",
  "account_bank": "044"
}
```

### Response — Success
```json
{
  "status": "success",
  "message": "Account resolved",
  "data": {
    "account_number": "0123456789",
    "account_name": "JOHN DOE",
    "bank_code": "044"
  }
}
```

### Response — Error
```json
{
  "status": "error",
  "message": "No account was found for the data provided",
  "data": null
}
```

---

## 4. File Upload & Processing (Internal API)

### Upload
```
POST /api/upload HTTP/1.1
Content-Type: multipart/form-data

file: @October_New_Accounts.xlsx
```

### Response (HTMX partial)
```html
<div class="file-card" id="file-abc123">
  <div class="file-status">Needs Mapping</div>
  <div class="file-name">October_New_Accounts.xlsx</div>
  <div class="health-report">
    <ul>
      <li class="pass">✓ Rows detected: 245</li>
      <li class="pass">✓ Headers: TIN, ACCOUNT_NAME, NUBAN, BVN, PHONE</li>
      <li class="warn">⚠ Sheet named "Sheet1" — verifying correctness</li>
    </ul>
  </div>
</div>
```

### Process
```
POST /api/process/abc123
Content-Type: application/x-www-form-urlencoded

headers={"TAXPAYER_ID":"TIN","ACCOUNT_NAME":"ACCOUNT_NAME","NUBAN":"NUBAN","BVN":"BVN","PHONE":"PHONE NO 1","ADDRESS":"RESIDENTIAL ADDRESS","DATE":"DATE"}
```

### Cleaned CSV Output
```csv
TAXPAYER_ID,ACCOUNT_NAME,NUBAN,BVN,PHONE,ADDRESS,DATE
12345678-0001,JOHN DOE,0123456789,12345678901,08031234567,123 ABAK ROAD UYO,2025-10-01
12345678-0002,JANE DOE,0987654321,98765432109,08039876543,45 ORON ROAD UYO,2025-10-02
```

---

## 5. NUBAN Resolution File Output

### Input Row (before)
```csv
ACCOUNT_NAME,ACCOUNT_NUMBER,BANK,BRANCH
JOHN DOE,0123456789,044,UYO
```

### Output Row (after)
```csv
ACCOUNT_NAME,ACCOUNT_NUMBER,BANK,BRANCH,VERIFIED_NAME
JOHN DOE,0123456789,044,UYO,JOHN DOE
```

### On failure
```csv
ACCOUNT_NAME,ACCOUNT_NUMBER,BANK,BRANCH,VERIFIED_NAME
UNKNOWN,0000000000,044,UYO,Resolution Failed
```
