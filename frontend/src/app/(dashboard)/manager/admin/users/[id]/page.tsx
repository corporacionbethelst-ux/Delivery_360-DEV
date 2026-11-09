"use client";
import { useParams } from "next/navigation";
import UserAccountForm from "@/components/users/UserAccountForm";
export default function EditUserPage() {
  const params = useParams();
  return (
    <UserAccountForm id={typeof params.id === "string" ? params.id : ""} />
  );
}
