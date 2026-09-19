import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";
import {
  Avatar,
  AvatarFallback,
  AvatarImage
} from "@/components/elevenlabs/ui/avatar";
const Message = ({ className, from, ...props }) => <div
  className={cn(
    "group flex w-full items-end justify-end gap-2 py-4",
    from === "user" ? "is-user" : "is-assistant flex-row-reverse justify-end",
    className
  )}
  {...props}
/>;
const messageContentVariants = cva(
  "is-user:dark flex flex-col gap-2 overflow-hidden rounded-lg text-sm",
  {
    variants: {
      variant: {
        contained: [
          "max-w-[80%] px-4 py-3",
          "group-[.is-user]:bg-primary group-[.is-user]:text-primary-foreground",
          "group-[.is-assistant]:bg-secondary group-[.is-assistant]:text-foreground"
        ],
        flat: [
          "group-[.is-user]:max-w-[80%] group-[.is-user]:bg-secondary group-[.is-user]:px-4 group-[.is-user]:py-3 group-[.is-user]:text-foreground",
          "group-[.is-assistant]:text-foreground"
        ]
      }
    },
    defaultVariants: {
      variant: "contained"
    }
  }
);
const MessageContent = ({
  children,
  className,
  variant,
  ...props
}) => <div
  className={cn(messageContentVariants({ variant, className }))}
  {...props}
>
    {children}
  </div>;
const MessageAvatar = ({
  src,
  name,
  className,
  ...props
}) => <Avatar className={cn("ring-border size-8 ring-1", className)} {...props}>
    <AvatarImage alt="" className="mt-0 mb-0" src={src} />
    <AvatarFallback>{name?.slice(0, 2) || "ME"}</AvatarFallback>
  </Avatar>;
export {
  Message,
  MessageAvatar,
  MessageContent
};
