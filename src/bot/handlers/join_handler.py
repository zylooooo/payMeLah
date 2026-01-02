from telegram import Update
from telegram.ext import ContextTypes
from infrastructure import get_db
from services import GroupService
from shared import (
    GroupNotFoundException,
    GroupMemberAlreadyExistsException,
    UnauthorizedGroupJoinException
)
import logging

logger = logging.getLogger(__name__)

ERROR_MSG = "An unexpected error has occurred. Please try again later."


async def handle_join_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int
) -> None:
    """
    Handle joining a group via deeplink.
    Validates Telegram group membership and adds user to the expense group.
    Sends confirmation to both user and the Telegram group chat.

    Args:
        update: Telegram Update object
        context: Bot context
        group_id: The ID of the group to join
    """
    telegram_user = update.effective_user
    if not telegram_user:
        logger.warning("Join attempt without user information")
        return
    
    logger.info(f"User {telegram_user.id} attempting to join group {group_id} via deeplink")
    
    try:
        async with get_db() as db:
            # Get group info first
            group = await GroupService.get_group_by_id(db, group_id)
            if not group:
                await update.message.reply_text(
                    "<b>Group not found.</b>\n\n"
                    "The group may have been deleted or the link is invalid.",
                    parse_mode="HTML"
                )
                return
            
            telegram_chat_id = group.get('telegram_chat_id')
            if not telegram_chat_id:
                logger.error(f"Group {group_id} has no telegram_chat_id")
                await update.message.reply_text(
                    "<b>Unable to verify group membership.</b>\n\n"
                    "Please contact the group administrator.",
                    parse_mode="HTML"
                )
                return
            
            # Verify user is in the Telegram group
            telegram_group_member_ids = await _get_telegram_group_member_ids(
                context.bot,
                telegram_chat_id,
                telegram_user.id
            )
            
            if telegram_group_member_ids is None:
                await update.message.reply_text(
                    "<b>Unable to verify Telegram group membership.</b>\n\n"
                    "Please ensure you are a member of the Telegram group chat "
                    "and that the bot has administrator privileges.",
                    parse_mode="HTML"
                )
                return
            
            # Prepare user data for service layer
            user_data = {
                'id': telegram_user.id,
                'username': telegram_user.username,
                'first_name': telegram_user.first_name,
                'last_name': telegram_user.last_name
            }
            
            # Join the group via service
            await GroupService.join_group(
                db,
                group_id=group_id,
                user_data=user_data,
                telegram_group_member_ids=telegram_group_member_ids
            )
            
            # Send success message to user
            user_display_name = telegram_user.first_name or telegram_user.username
            success_msg = (
                f"<b>Successfully joined {group['name']}!</b>\n\n"
                "You can now start splitting bills with your group members.\n\n"
                "Use /groups to view all your groups."
            )
            await update.message.reply_text(success_msg, parse_mode="HTML")
            
            # Send notification to Telegram group chat
            group_notification = (
                f"<b>{user_display_name}</b> has joined the expense group "
                f"<b>{group['name']}</b>!"
            )
            try:
                await context.bot.send_message(
                    chat_id=telegram_chat_id,
                    text=group_notification,
                    parse_mode="HTML"
                )
            except Exception as e:
                # Log but don't fail if notification can't be sent
                logger.warning(f"Could not send join notification to group chat: {e}")
            
            logger.info(f"User {telegram_user.id} successfully joined group {group_id}")
            
    except GroupNotFoundException:
        await update.message.reply_text(
            "<b>Group not found.</b>\n\n"
            "The group may have been deleted.",
            parse_mode="HTML"
        )
    except GroupMemberAlreadyExistsException:
        await update.message.reply_text(
            "<b>You are already a member of this group.</b>\n\n"
            "Use /groups to view all your groups.",
            parse_mode="HTML"
        )
    except UnauthorizedGroupJoinException:
        await update.message.reply_text(
            "<b>You cannot join this group.</b>\n\n"
            "You must be a member of the Telegram group chat to join this expense group.\n"
            "Please ask the group owner to add you to the Telegram group first.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error joining group: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MSG)


async def _get_telegram_group_member_ids(
    bot,
    telegram_chat_id: int,
    user_id: int
) -> list[int] | None:
    """
    Get list of Telegram group member IDs and verify the specific user is a member.
    
    Due to Telegram API limitations, we can only get administrators list directly.
    For regular members, we verify by checking if we can get their chat member info.
    
    Args:
        bot: Telegram Bot instance
        telegram_chat_id: The Telegram chat ID
        user_id: The user ID to verify membership for
    
    Returns:
        List of member IDs if user is verified, None if verification failed
    """
    member_ids = []
    
    try:
        # Get administrators (they're always members)
        admins = await bot.get_chat_administrators(telegram_chat_id)
        for admin in admins:
            member_ids.append(admin.user.id)
        
        # Check if the specific user is a member
        try:
            member_info = await bot.get_chat_member(
                chat_id=telegram_chat_id,
                user_id=user_id
            )
            
            # Check if user is actually a member (not left/kicked/restricted)
            if member_info.status in ['left', 'kicked']:
                logger.warning(f"User {user_id} is not a member of Telegram group {telegram_chat_id}")
                return None
            
            # User is a member, add to list
            if user_id not in member_ids:
                member_ids.append(user_id)
                
        except Exception as e:
            logger.warning(f"Could not verify user {user_id} membership: {e}")
            return None
            
        return member_ids
        
    except Exception as e:
        logger.error(f"Error getting Telegram group members: {e}", exc_info=True)
        return None
