# Client Demo Rehearsal

Use this script to present the simplified safe verification flow to a client.

## Demo Script

1. **Login as admin**
   - Open the dashboard.
   - Sign in with the admin account.

2. **Start a new verification call**
   - Enter recipient details.
   - Select the country code and phone number.
   - Click **Start verification call**.

3. **Show the simplified dashboard**
   - Point out the clean light interface.
   - Explain that the dashboard focuses on the current call, admin decision, and important activity only.

4. **Show the mobile simulator on the right**
   - Explain that this represents the recipient phone.
   - The admin dashboard remains separate from the recipient experience.

5. **Recipient presses 1**
   - In the mobile simulator, press **1** to continue.
   - Explain that consent is required before code entry.

6. **Explain the official 6-digit code**
   - Say: “The recipient receives a 6-digit code from the client’s official verification system.”
   - Clarify that this is not a Messenger, Facebook, WhatsApp, email, bank, or third-party OTP code.

7. **Recipient enters a 6-digit test code**
   - Type a 6-digit test code on the mobile keypad.
   - The call moves to pending admin verification.

8. **Show pending admin verification**
   - Point out the admin review card.
   - Explain that the backend does not automatically accept the code.

9. **Show masked code only**
   - The admin sees only the masked format, for example `****42`.
   - Explain that the full code is not displayed in the dashboard or audit feed.

10. **Admin approves**
    - Click **Approve verification**.
    - Explain that the admin/operator makes the final decision manually.

11. **Show verification completed**
    - Confirm the call status changes to completed.
    - Show the important activity feed updating.

12. **Show technical logs only if asked**
    - Leave technical logs hidden by default.
    - If the client asks for audit details, toggle **Show technical logs**.

## Talking Points

- The system does **not** collect third-party OTPs.
- The system does **not** ask for Messenger, Facebook, WhatsApp, email, bank, card, password, or external service codes.
- The recipient enters only a 6-digit code from the client’s official verification system.
- There is **no auto-verification** and no AI verification.
- The admin manually approves or rejects the verification.
- The full code is not displayed in the dashboard.
- Technical events are stored internally but hidden by default in the simplified UI.
- Asterisk or a provider API can replace the local mobile simulator for real telephony integration.

## Fallback Answer

If the client asks for Messenger/Facebook/WhatsApp/email/bank OTP collection:

> For compliance and user safety, this system does not capture third-party OTPs or external service codes. It supports only verification codes issued by your official verification system. The recipient enters that official 6-digit code during the call, and the admin manually approves or rejects the verification.

