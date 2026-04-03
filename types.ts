// types.ts — shared across all modules. Do not modify locally.

export interface Patient {
  id: string
  firstName: string
  lastName: string
  dob: string           // "YYYY-MM-DD"
  phone: string         // E.164 e.g. "+19195551234"
  email: string
  smsOptIn: boolean
}

export interface Doctor {
  id: string
  name: string
  specialty: string
  bodyParts: string[]   // used for semantic matching
  slots: Slot[]
}

export interface Slot {
  id: string
  doctorId: string
  datetime: string      // ISO 8601
  durationMinutes: number
  booked: boolean
}

export interface Appointment {
  id: string
  patientId: string
  doctorId: string
  slotId: string
  reason: string
  confirmedAt: string
  emailSent: boolean
  smsSent: boolean
}

export interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: string
}

export interface Session {
  id: string
  patient?: Patient
  appointment?: Appointment
  messages: Message[]
  createdAt: string
  lastActiveAt: string
}

export type Intent =
  | "INTAKE"
  | "SCHEDULING"
  | "RX_REFILL"
  | "OFFICE_INFO"
  | "CALL_REQUESTED"
  | "COMPLETED"
  | "OUT_OF_SCOPE"

export interface ChatRequest {
  sessionId: string
  message: string
}

export interface ChatResponse {
  reply: string
  intent: Intent
  session: Session
}
